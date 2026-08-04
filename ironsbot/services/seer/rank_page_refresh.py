# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.player_request_protection import (
    PlayerRequestPausedError,
)
from ironsbot.services.seer.rank_page_refresh_models import (
    RankPageRefreshFailure,
    RankPageRefreshResult,
)
from ironsbot.services.seer.rank_page_refresh_selection import (
    preview_rank_page_refresh_targets,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ironsbot.config.models.seer import RankPageRefreshConfig
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.rank import RankService
    from ironsbot.services.seer.rank_page_refresh_models import RankPageRefreshTarget

    HeadlessGameSource = HeadlessGame | Callable[[], HeadlessGame]


logger = logging.getLogger(__name__)
RANK_PAGE_REFRESH_BACKOFF_SECONDS = 300.0


def _is_rank_page_refresh_connection_error(error: Exception) -> bool:
    return isinstance(
        error,
        (
            asyncio.TimeoutError,
            BrokenPipeError,
            ConnectionError,
            DisconnectedError,
            NotLoggedInError,
            OSError,
            SocketRecvError,
            TimeoutError,
        ),
    )


@dataclass(slots=True)
class RankPageRefreshService:
    config: RankPageRefreshConfig
    rank: RankService
    requests: PlayerRequestProtectionService | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _backoff_until: float = field(default=0.0, init=False)

    def preview(
        self,
        rank_keys: Sequence[str] | None = None,
        *,
        limit: int | None = None,
    ) -> list[RankPageRefreshTarget]:
        return preview_rank_page_refresh_targets(
            self.config,
            self.rank,
            rank_keys,
            limit=limit,
        )

    def backoff_remaining(self) -> float:
        return max(self._backoff_until - time.monotonic(), 0.0)

    async def refresh(
        self,
        game: HeadlessGameSource,
        rank_keys: Sequence[str] | None = None,
        *,
        background: bool = False,
        user_id: int | None = None,
        max_parallelism: int = 1,
    ) -> RankPageRefreshResult:
        if self._lock.locked():
            logger.info(
                "rank page cache auto refresh skipped: previous run still active"
            )
            return RankPageRefreshResult(targets=[])

        backoff_remaining = self.backoff_remaining()
        if backoff_remaining > 0:
            logger.info(
                "rank page cache auto refresh skipped: backoff %.0fs remaining",
                backoff_remaining,
            )
            return RankPageRefreshResult(targets=[])

        async with self._lock:
            return await self._refresh_unlocked(
                game,
                rank_keys,
                background=background,
                user_id=user_id,
                max_parallelism=max_parallelism,
            )

    async def _refresh_unlocked(
        self,
        game: HeadlessGameSource,
        rank_keys: Sequence[str] | None,
        *,
        background: bool,
        user_id: int | None,
        max_parallelism: int,
    ) -> RankPageRefreshResult:
        page_budget = self._page_budget()
        targets = self.preview(rank_keys, limit=page_budget)
        parallelism = min(max(max_parallelism, 1), len(targets))
        result = RankPageRefreshResult(
            targets=targets,
            parallelism=parallelism,
        )
        if not targets:
            return result

        slot_times = self._page_slot_times(
            target_count=len(targets),
            background=background,
        )

        result_lock = asyncio.Lock()
        stopped = asyncio.Event()
        active_refreshes = asyncio.Semaphore(parallelism)
        attempted = 0
        connection_failures = 0

        async def refresh_target(
            target: RankPageRefreshTarget,
            *,
            slot_at: float,
        ) -> None:
            nonlocal attempted, connection_failures
            await self._wait_for_slot(slot_at)
            if stopped.is_set():
                return
            async with active_refreshes:
                try:
                    worker_id = await self._refresh_target(
                        game,
                        target,
                        background=background,
                        user_id=user_id,
                    )
                except Exception as error:  # noqa: BLE001
                    connection_error = _is_rank_page_refresh_connection_error(error)
                    async with result_lock:
                        attempted += 1
                        if connection_error:
                            connection_failures += 1
                        result.failures.append(
                            RankPageRefreshFailure(
                                target=target,
                                reason=str(error) or type(error).__name__,
                            )
                        )
                    logger.warning(
                        "rank page cache refresh failed: target=%s %s-%s "
                        "reason=%s",
                        target.rank_key,
                        target.start_rank,
                        target.end_rank,
                        error or type(error).__name__,
                    )
                    if isinstance(error, PlayerRequestPausedError):
                        stopped.set()
                        logger.info(
                            "rank page cache auto refresh stopped: "
                            "player requests paused"
                        )
                    return

                async with result_lock:
                    attempted += 1
                    result.refreshed.append(target)
                    if worker_id is not None:
                        result.worker_page_counts[worker_id] = (
                            result.worker_page_counts.get(worker_id, 0) + 1
                        )
                logger.info(
                    "rank page cache refreshed: target=%s %s-%s worker=%s",
                    target.rank_key,
                    target.start_rank,
                    target.end_rank,
                    worker_id if worker_id is not None else "unknown",
                )

        await asyncio.gather(
            *(
                refresh_target(target, slot_at=slot_times[index])
                for index, target in enumerate(targets)
            )
        )
        if attempted > 0 and connection_failures == attempted:
            self._backoff_until = time.monotonic() + RANK_PAGE_REFRESH_BACKOFF_SECONDS
            logger.warning(
                "rank page cache auto refresh enters backoff: all %s dispatched "
                "pages failed with connection errors",
                attempted,
            )
        return result

    async def _refresh_target(
        self,
        game: HeadlessGameSource,
        target: RankPageRefreshTarget,
        *,
        background: bool,
        user_id: int | None,
    ) -> int | None:
        async def fetch() -> int | None:
            active_game = game() if callable(game) else game
            action_name = "后台刷榜缓存" if background else "手动刷新榜单缓存"
            with active_game.operations.track(
                action_name,
                (
                    f"{target.rank_key} {target.start_rank}-{target.end_rank}名"
                    f"（{target.reason}）"
                ),
                source=action_name,
                background=background,
            ):
                await self.rank.fetch_range(
                    active_game,
                    key=target.spec.key,
                    sub_key=target.spec.sub_key,
                    start=target.raw_start,
                    count=target.raw_end - target.raw_start + 1,
                    use_cache=False,
                )
            return getattr(active_game, "user_id", None)

        if self.requests is None:
            return await fetch()
        return await self.requests.run(
            fetch,
            user_id=user_id,
            label="后台刷榜缓存" if background else "手动刷新榜单缓存",
            background=background,
        )

    def _page_slot_times(
        self,
        *,
        target_count: int,
        background: bool,
    ) -> list[float]:
        started_at = time.monotonic()
        if target_count <= 0:
            return []

        minimum_gap = self.config.request_interval_seconds
        if not background or self.config.interval_minutes <= 0:
            spacing = minimum_gap + random.uniform(  # nosec B311
                0,
                self.config.request_jitter_seconds,
            )
            return [started_at + index * spacing for index in range(target_count)]

        nominal_spacing = self.config.interval_minutes * 60 / target_count
        spacing = max(minimum_gap, nominal_spacing)
        jitter_limit = min(self.config.request_jitter_seconds, spacing * 0.4)
        slots = [started_at]
        for index in range(1, target_count):
            nominal_slot = started_at + index * spacing
            jitter = random.uniform(-jitter_limit, jitter_limit)  # nosec B311
            slots.append(max(nominal_slot + jitter, slots[-1] + minimum_gap))
        return slots

    def _page_budget(self) -> int:
        minimum = self.config.pages_per_run_min
        if minimum <= 0:
            return self.config.pages_per_run
        return random.randint(minimum, self.config.pages_per_run)  # nosec B311

    @staticmethod
    async def _wait_for_slot(slot_at: float) -> None:
        delay = slot_at - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
