# SPDX-License-Identifier: GPL-3.0-or-later
"""Concurrent page scheduling for one player's independent leaderboards."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Generic, NoReturn, TypeVar

from anyio import create_task_group

from ironsbot.core.rank_lookup_context import rank_page_request_timeout
from ironsbot.services.seer.rank_models import RankLookupResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator, Sequence

    from ironsbot.config.models.seer import PlayerRankLookupConfig


_LOGGER = logging.getLogger("ironsbot.seer.rank_player_scheduler")
_CURRENT_SCHEDULER: ContextVar["PlayerRankPageScheduler | None"] = ContextVar(
    "player_rank_page_scheduler",
    default=None,
)
_CURRENT_LOOKUP_ID: ContextVar[str | None] = ContextVar(
    "player_rank_lookup_id",
    default=None,
)
T = TypeVar("T")


class PlayerRankPagePriority(IntEnum):
    """Ordering for pages inside one foreground player-rank workflow."""

    RECENT_CACHE_ANCHOR = 0
    CACHED_ANCHOR = 10
    SEARCH = 20


@dataclass(frozen=True, slots=True)
class PlayerRankLookupJob:
    """One independent leaderboard lookup in a player detail request."""

    id: str
    title: str
    key: int
    sub_key: int
    user_id: int
    target_score: int | None
    operation: Callable[[], Awaitable[RankLookupResult]]
    priority_group: int = 3
    priority_rank: int = 2**31 - 1
    priority_reason: str = "unknown"


@dataclass(slots=True)
class _PageRequest(Generic[T]):
    lookup_id: str
    title: str
    operation: Callable[[], Awaitable[T]]
    future: asyncio.Future[T]
    concurrent: bool = False
    attempt: int = 0
    priority: PlayerRankPagePriority = PlayerRankPagePriority.SEARCH
    phase: str = "search"
    timeout_seconds: float | None = None
    max_retries: int | None = None


@dataclass(slots=True)
class _LookupStats:
    page_requests: int = 0
    retries: int = 0


class PlayerRankPageScheduler:
    """Run independent boards in parallel while keeping every board ordered."""

    def __init__(self, config: PlayerRankLookupConfig) -> None:
        self._config = config
        self._deadline: float | None = None
        self._queue: deque[_PageRequest[Any]] = deque()
        self._queue_ready = asyncio.Event()
        self._closed = False
        self._stats: dict[str, _LookupStats] = {}
        self._active_lookup_counts: dict[str, int] = {}
        self._active_pages = 0

    @contextmanager
    def lookup_context(self, lookup_id: str) -> Generator[None, None, None]:
        token = _CURRENT_LOOKUP_ID.set(lookup_id)
        try:
            yield
        finally:
            _CURRENT_LOOKUP_ID.reset(token)

    async def fetch_page(  # noqa: PLR0913
        self,
        title: str,
        operation: Callable[[], Awaitable[T]],
        *,
        priority: PlayerRankPagePriority = PlayerRankPagePriority.SEARCH,
        phase: str = "search",
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> T:
        return await self._submit_page(
            title,
            operation,
            priority=priority,
            phase=phase,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    async def fetch_pages(  # noqa: PLR0913
        self,
        title: str,
        operations: Sequence[Callable[[], Awaitable[T]]],
        *,
        priority: PlayerRankPagePriority = PlayerRankPagePriority.SEARCH,
        phase: str = "search",
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> list[T]:
        """Run an explicit batch of independent probes for the current board."""

        tasks = (
            self._submit_page(
                title,
                operation,
                concurrent=True,
                priority=priority,
                phase=phase,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
            for operation in operations
        )
        return await asyncio.gather(*tasks)

    async def fetch_parallel_page(  # noqa: PLR0913
        self,
        title: str,
        operation: Callable[[], Awaitable[T]],
        *,
        priority: PlayerRankPagePriority = PlayerRankPagePriority.SEARCH,
        phase: str = "search",
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> T:
        return await self._submit_page(
            title,
            operation,
            concurrent=True,
            priority=priority,
            phase=phase,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    async def _submit_page(  # noqa: PLR0913
        self,
        title: str,
        operation: Callable[[], Awaitable[T]],
        *,
        concurrent: bool = False,
        priority: PlayerRankPagePriority = PlayerRankPagePriority.SEARCH,
        phase: str = "search",
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> T:
        if self._closed or self._timed_out():
            raise TimeoutError("玩家榜单查询总时间已到")
        lookup_id = _CURRENT_LOOKUP_ID.get()
        if not lookup_id:
            return await operation()

        future: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        self._queue.append(
            _PageRequest(
                lookup_id=lookup_id,
                title=title,
                operation=operation,
                future=future,
                concurrent=concurrent,
                priority=priority,
                phase=phase,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
        )
        self._queue_ready.set()
        return await future

    def lookup_stats(self, lookup_id: str) -> _LookupStats:
        return self._stats.get(lookup_id, _LookupStats())

    async def close(self) -> None:
        self._closed = True
        self._expire_pending_requests()
        self._queue_ready.set()

    async def run(self) -> None:
        """Dispatch every ready board page; the shared worker pool caps I/O."""

        async with create_task_group() as task_group:
            while not self._closed or self._active_pages:
                await self._queue_ready.wait()
                self._queue_ready.clear()
                if self._closed:
                    continue
                if self._timed_out():
                    self._expire_pending_requests()
                    continue
                while request := self._next_ready_request():
                    self._active_lookup_counts[request.lookup_id] = (
                        self._active_lookup_counts.get(request.lookup_id, 0) + 1
                    )
                    self._active_pages += 1
                    task_group.start_soon(
                        self._process_request,
                        request,
                        name=(
                            "player-rank-page:"
                            f"{request.lookup_id}:{request.title}"
                        ),
                    )

    def _next_ready_request(self) -> _PageRequest[Any] | None:
        candidates = [
            (index, request)
            for index, request in enumerate(self._queue)
            if request.concurrent
            or not self._active_lookup_counts.get(request.lookup_id, 0)
        ]
        if not candidates:
            return None
        index, request = min(candidates, key=lambda item: (item[1].priority, item[0]))
        del self._queue[index]
        return request

    async def _process_request(  # noqa: C901
        self,
        request: _PageRequest[Any],
    ) -> None:
        stats = self._stats.setdefault(request.lookup_id, _LookupStats())
        stats.page_requests += 1
        if self._deadline is None:
            self._deadline = time.monotonic() + self._config.total_timeout_seconds
        timeout_seconds = request.timeout_seconds or self._config.page_timeout_seconds
        max_retries = (
            self._config.page_retry_count
            if request.max_retries is None
            else request.max_retries
        )
        started_at = time.monotonic()
        timeout_token = rank_page_request_timeout.set(timeout_seconds)
        _LOGGER.info(
            "player rank page dispatched: lookup=%s title=%s phase=%s "
            "priority=%s timeout=%.3fs attempt=%s",
            request.lookup_id,
            request.title,
            request.phase,
            request.priority.name.lower(),
            timeout_seconds,
            request.attempt + 1,
        )
        try:
            remaining_seconds = self._deadline - time.monotonic()
            if remaining_seconds <= 0:
                self._raise_total_timeout()
            result = await asyncio.wait_for(
                request.operation(),
                timeout=min(remaining_seconds, timeout_seconds),
            )
        except (TimeoutError, asyncio.TimeoutError) as error:
            timeout_error = TimeoutError(str(error) or "玩家榜单页查询超时")
            if (
                request.attempt < max_retries
                and not self._closed
                and not self._timed_out()
            ):
                request.attempt += 1
                stats.retries += 1
                self._queue.append(request)
                _LOGGER.info(
                    "player rank page timed out; retry queued: lookup=%s title=%s "
                    "phase=%s attempt=%s elapsed=%.3fs",
                    request.lookup_id,
                    request.title,
                    request.phase,
                    request.attempt,
                    time.monotonic() - started_at,
                )
            elif not request.future.done():
                request.future.set_exception(timeout_error)
                _LOGGER.warning(
                    "player rank page timed out permanently: lookup=%s title=%s "
                    "phase=%s attempts=%s elapsed=%.3fs",
                    request.lookup_id,
                    request.title,
                    request.phase,
                    request.attempt + 1,
                    time.monotonic() - started_at,
                )
        except Exception as error:  # noqa: BLE001
            if not request.future.done():
                request.future.set_exception(error)
            _LOGGER.warning(
                "player rank page failed: lookup=%s title=%s phase=%s "
                "error=%s elapsed=%.3fs",
                request.lookup_id,
                request.title,
                request.phase,
                type(error).__name__,
                time.monotonic() - started_at,
            )
        else:
            if not request.future.done():
                request.future.set_result(result)
            _LOGGER.info(
                "player rank page completed: lookup=%s title=%s phase=%s "
                "elapsed=%.3fs",
                request.lookup_id,
                request.title,
                request.phase,
                time.monotonic() - started_at,
            )
        finally:
            rank_page_request_timeout.reset(timeout_token)
            active_count = self._active_lookup_counts.get(request.lookup_id, 0) - 1
            if active_count > 0:
                self._active_lookup_counts[request.lookup_id] = active_count
            else:
                self._active_lookup_counts.pop(request.lookup_id, None)
            self._active_pages = max(0, self._active_pages - 1)
            self._queue_ready.set()

    def _timed_out(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline

    @staticmethod
    def _raise_total_timeout() -> NoReturn:
        raise TimeoutError("玩家榜单查询总时间已到")

    def _expire_pending_requests(self) -> None:
        while self._queue:
            request = self._queue.popleft()
            if not request.future.done():
                request.future.set_exception(TimeoutError("玩家榜单查询已结束"))


def current_player_rank_page_scheduler() -> PlayerRankPageScheduler | None:
    return _CURRENT_SCHEDULER.get()


async def run_player_rank_lookup_jobs(
    jobs: Sequence[PlayerRankLookupJob],
    config: PlayerRankLookupConfig,
) -> dict[str, RankLookupResult]:
    """Run independent lookups together; each board remains page-ordered."""

    if not jobs:
        return {}
    scheduler = PlayerRankPageScheduler(config)
    token = _CURRENT_SCHEDULER.set(scheduler)
    ordered_jobs = sorted(
        jobs,
        key=lambda job: (job.priority_group, job.priority_rank, job.id),
    )

    async def run_job(job: PlayerRankLookupJob) -> tuple[str, RankLookupResult]:
        _LOGGER.info(
            "player rank lookup scheduled: id=%s title=%s priority=%s "
            "priority_rank=%s target_score=%s",
            job.id,
            job.title,
            job.priority_reason,
            job.priority_rank,
            job.target_score,
        )
        with scheduler.lookup_context(job.id):
            result = await job.operation()
        stats = scheduler.lookup_stats(job.id)
        _LOGGER.info(
            "player rank lookup completed: id=%s title=%s rank=%s failure=%s "
            "cache_age=%s recent_anchor=%s recent_fallback=%s "
            "online_pages=%s scheduler_pages=%s retries=%s page_starts=%s",
            job.id,
            job.title,
            result.rank,
            result.failure,
            (
                None
                if result.cost.cached_rank_age_seconds is None
                else round(result.cost.cached_rank_age_seconds, 3)
            ),
            result.cost.used_recent_cache_anchor,
            result.cost.used_recent_cache_fallback,
            result.cost.online_page_fetches,
            stats.page_requests,
            stats.retries,
            tuple(start + 1 for start in result.cost.page_starts),
        )
        return job.id, result

    results: list[tuple[str, RankLookupResult] | BaseException] = []
    try:
        async with create_task_group() as task_group:
            task_group.start_soon(
                scheduler.run,
                name="player-rank-page-scheduler",
            )
            try:
                results = await asyncio.gather(
                    *(run_job(job) for job in ordered_jobs),
                    return_exceptions=True,
                )
            finally:
                await scheduler.close()
        completed: list[tuple[str, RankLookupResult]] = []
        for job, result in zip(ordered_jobs, results, strict=True):
            if not isinstance(result, BaseException):
                completed.append(result)
                continue
            if isinstance(result, asyncio.CancelledError):
                raise result
            _LOGGER.warning(
                "player rank lookup failed: id=%s title=%s",
                job.id,
                job.title,
                exc_info=result,
            )
            completed.append((job.id, _failed_lookup_result(job, result)))
        resolved = dict(completed)
        _LOGGER.info(
            "player rank lookup batch completed: jobs=%s total_budget=%.3fs "
            "scheduler_pages=%s retries=%s recent_fallbacks=%s failures=%s",
            len(resolved),
            config.total_timeout_seconds,
            sum(scheduler.lookup_stats(job.id).page_requests for job in ordered_jobs),
            sum(scheduler.lookup_stats(job.id).retries for job in ordered_jobs),
            sum(
                item.cost.used_recent_cache_fallback
                for item in resolved.values()
            ),
            sum(item.failure is not None for item in resolved.values()),
        )
        return resolved
    finally:
        _CURRENT_SCHEDULER.reset(token)


def _failed_lookup_result(
    job: PlayerRankLookupJob,
    error: BaseException,
) -> RankLookupResult:
    failure = "查询超时" if isinstance(error, TimeoutError) else "查询失败"
    return RankLookupResult(
        title=job.title,
        score_name="",
        score=job.target_score,
        searched_limit=0,
        failure=failure,
    )
