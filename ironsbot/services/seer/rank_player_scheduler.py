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
    attempt: int = 0


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
        self._active_lookup_ids: set[str] = set()
        self._active_pages = 0

    @contextmanager
    def lookup_context(self, lookup_id: str) -> Generator[None, None, None]:
        token = _CURRENT_LOOKUP_ID.set(lookup_id)
        try:
            yield
        finally:
            _CURRENT_LOOKUP_ID.reset(token)

    async def fetch_page(self, title: str, operation: Callable[[], Awaitable[T]]) -> T:
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
                    self._active_lookup_ids.add(request.lookup_id)
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
        for index, request in enumerate(self._queue):
            if request.lookup_id not in self._active_lookup_ids:
                del self._queue[index]
                return request
        return None

    async def _process_request(self, request: _PageRequest[Any]) -> None:
        stats = self._stats.setdefault(request.lookup_id, _LookupStats())
        stats.page_requests += 1
        if self._deadline is None:
            self._deadline = time.monotonic() + self._config.total_timeout_seconds
        timeout_token = rank_page_request_timeout.set(self._config.page_timeout_seconds)
        try:
            remaining_seconds = self._deadline - time.monotonic()
            if remaining_seconds <= 0:
                self._raise_total_timeout()
            result = await asyncio.wait_for(
                request.operation(),
                timeout=remaining_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError) as error:
            timeout_error = TimeoutError(str(error) or "玩家榜单页查询超时")
            if (
                request.attempt < self._config.page_retry_count
                and not self._closed
                and not self._timed_out()
            ):
                request.attempt += 1
                stats.retries += 1
                self._queue.append(request)
                _LOGGER.info(
                    "player rank page timed out; retry queued: lookup=%s title=%s "
                    "attempt=%s",
                    request.lookup_id,
                    request.title,
                    request.attempt,
                )
            elif not request.future.done():
                request.future.set_exception(timeout_error)
                _LOGGER.warning(
                    "player rank page timed out permanently: lookup=%s title=%s "
                    "attempts=%s",
                    request.lookup_id,
                    request.title,
                    request.attempt + 1,
                )
        except Exception as error:  # noqa: BLE001
            if not request.future.done():
                request.future.set_exception(error)
        else:
            if not request.future.done():
                request.future.set_result(result)
        finally:
            rank_page_request_timeout.reset(timeout_token)
            self._active_lookup_ids.discard(request.lookup_id)
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
            "online_pages=%s scheduler_pages=%s retries=%s",
            job.id,
            job.title,
            result.rank,
            result.failure,
            result.cost.online_page_fetches,
            stats.page_requests,
            stats.retries,
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
        return dict(completed)
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
