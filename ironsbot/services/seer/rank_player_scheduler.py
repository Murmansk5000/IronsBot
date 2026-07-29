# SPDX-License-Identifier: GPL-3.0-or-later
"""Cooperative page scheduling for one player's multi-leaderboard lookup."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from ironsbot.core.rank_lookup_context import rank_page_request_timeout

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator, Sequence

    from ironsbot.config.models.seer import PlayerRankLookupConfig
    from ironsbot.services.seer.rank_models import RankLookupResult


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
class _PageRequest:
    lookup_id: str
    title: str
    operation: Callable[[], Awaitable[T]]
    future: asyncio.Future[T]
    attempt: int = 0


@dataclass(slots=True)
class _LookupStats:
    page_requests: int = 0
    turns: int = 0
    retries: int = 0


class PlayerRankPageScheduler:
    """Serialize online rank pages while rotating fairly between lookup jobs."""

    def __init__(self, config: PlayerRankLookupConfig) -> None:
        self._config = config
        self._deadline = time.monotonic() + config.total_timeout_seconds
        self._queue: deque[_PageRequest[Any]] = deque()
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
        self._stats: dict[str, _LookupStats] = {}
        self._active_lookup_id: str | None = None
        self._active_turn_pages = 0

    @contextmanager
    def lookup_context(self, lookup_id: str) -> Generator[None, None, None]:
        token = _CURRENT_LOOKUP_ID.set(lookup_id)
        try:
            yield
        finally:
            _CURRENT_LOOKUP_ID.reset(token)

    async def fetch_page(self, title: str, operation: Callable[[], Awaitable[T]]) -> T:
        if self._closed or time.monotonic() >= self._deadline:
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
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(
                self._run(),
                name="player-rank-page-scheduler",
            )
        return await future

    def lookup_stats(self, lookup_id: str) -> _LookupStats:
        return self._stats.get(lookup_id, _LookupStats())

    async def close(self) -> None:
        self._closed = True
        while self._queue:
            request = self._queue.popleft()
            if not request.future.done():
                request.future.set_exception(TimeoutError("玩家榜单查询已结束"))
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker

    async def _run(self) -> None:
        while self._queue and not self._closed:
            request = self._next_request()
            if request.future.done():
                continue
            if time.monotonic() >= self._deadline:
                request.future.set_exception(TimeoutError("玩家榜单查询总时间已到"))
                self._expire_pending_requests()
                return

            timeout_token = rank_page_request_timeout.set(
                self._config.page_timeout_seconds
            )
            stats = self._stats.setdefault(request.lookup_id, _LookupStats())
            stats.page_requests += 1
            stats.turns += 1
            try:
                result = await request.operation()
            except TimeoutError as error:
                if request.attempt < self._config.page_retry_count:
                    request.attempt += 1
                    stats.retries += 1
                    self._queue.append(request)
                    # A slow page never consumes the rest of its board's turn.
                    # Its retry stays at the tail so another board can progress.
                    self._end_active_turn()
                    _LOGGER.info(
                        "player rank page timed out; retry queued: lookup=%s title=%s "
                        "attempt=%s",
                        request.lookup_id,
                        request.title,
                        request.attempt,
                    )
                else:
                    request.future.set_exception(error)
                    _LOGGER.warning(
                        "player rank page timed out permanently: lookup=%s title=%s "
                        "attempts=%s",
                        request.lookup_id,
                        request.title,
                        request.attempt + 1,
                    )
            except Exception as error:  # noqa: BLE001
                request.future.set_exception(error)
            else:
                request.future.set_result(result)
            finally:
                rank_page_request_timeout.reset(timeout_token)

            # Let the lookup continue until it either queues its next page or
            # completes. This is what makes pages_per_turn a real consecutive
            # turn instead of merely a queue preference.
            await asyncio.sleep(0)

    def _next_request(self) -> _PageRequest[Any]:
        if (
            self._active_lookup_id is not None
            and self._active_turn_pages < self._config.pages_per_turn
        ):
            for index, request in enumerate(self._queue):
                if request.lookup_id == self._active_lookup_id:
                    del self._queue[index]
                    self._active_turn_pages += 1
                    return request

        request = self._queue.popleft()
        self._active_lookup_id = request.lookup_id
        self._active_turn_pages = 1
        return request

    def _end_active_turn(self) -> None:
        self._active_lookup_id = None
        self._active_turn_pages = 0

    def _expire_pending_requests(self) -> None:
        while self._queue:
            request = self._queue.popleft()
            if not request.future.done():
                request.future.set_exception(TimeoutError("玩家榜单查询总时间已到"))


def current_player_rank_page_scheduler() -> PlayerRankPageScheduler | None:
    return _CURRENT_SCHEDULER.get()


async def run_player_rank_lookup_jobs(
    jobs: Sequence[PlayerRankLookupJob],
    config: PlayerRankLookupConfig,
) -> dict[str, RankLookupResult]:
    """Run independent lookups concurrently, sharing one fair page queue."""

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
            "online_pages=%s scheduler_pages=%s turns=%s retries=%s",
            job.id,
            job.title,
            result.rank,
            result.failure,
            result.cost.online_page_fetches,
            stats.page_requests,
            stats.turns,
            stats.retries,
        )
        return job.id, result

    tasks = [
        asyncio.create_task(run_job(job), name=f"player-rank-{job.id}")
        for job in ordered_jobs
    ]
    try:
        results = await asyncio.gather(*tasks)
        return dict(results)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await scheduler.close()
        _CURRENT_SCHEDULER.reset(token)
