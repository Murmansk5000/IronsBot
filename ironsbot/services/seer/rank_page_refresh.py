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
    ) -> list[RankPageRefreshTarget]:
        return preview_rank_page_refresh_targets(self.config, self.rank, rank_keys)

    def backoff_remaining(self) -> float:
        return max(self._backoff_until - time.monotonic(), 0.0)

    async def refresh(
        self,
        game: HeadlessGameSource,
        rank_keys: Sequence[str] | None = None,
        *,
        background: bool = False,
        user_id: int | None = None,
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
            )

    async def _refresh_unlocked(
        self,
        game: HeadlessGameSource,
        rank_keys: Sequence[str] | None,
        *,
        background: bool,
        user_id: int | None,
    ) -> RankPageRefreshResult:
        targets = self.preview(rank_keys)
        if self.config.pages_per_run_min > 0 and targets:
            lower = min(self.config.pages_per_run_min, len(targets))
            upper = min(self.config.pages_per_run, len(targets))
            targets = targets[: random.randint(lower, upper)]  # nosec B311
        result = RankPageRefreshResult(targets=targets)
        if not targets:
            return result

        for index, target in enumerate(targets):
            if index > 0:
                await self._sleep_between_requests()
            try:
                await self._refresh_target(
                    game,
                    target,
                    background=background,
                    user_id=user_id,
                )
            except Exception as error:  # noqa: BLE001
                result.failures.append(
                    RankPageRefreshFailure(
                        target=target,
                        reason=str(error) or type(error).__name__,
                    )
                )
                if isinstance(error, PlayerRequestPausedError):
                    logger.info(
                        "rank page cache auto refresh stopped: player requests paused"
                    )
                    break
                if _is_rank_page_refresh_connection_error(error):
                    self._backoff_until = (
                        time.monotonic() + RANK_PAGE_REFRESH_BACKOFF_SECONDS
                    )
                    logger.warning(
                        "rank page cache auto refresh enters backoff after failure: %s",
                        error or type(error).__name__,
                    )
                    break
                continue
            result.refreshed.append(target)
        return result

    async def _refresh_target(
        self,
        game: HeadlessGameSource,
        target: RankPageRefreshTarget,
        *,
        background: bool,
        user_id: int | None,
    ) -> None:
        async def fetch() -> None:
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

        if self.requests is None:
            await fetch()
            return
        await self.requests.run(
            fetch,
            user_id=user_id,
            label="后台刷榜缓存" if background else "手动刷新榜单缓存",
            background=background,
        )

    async def _sleep_between_requests(self) -> None:
        delay = self.config.request_interval_seconds
        if self.config.request_jitter_seconds > 0:
            delay += random.uniform(  # nosec B311
                0,
                self.config.request_jitter_seconds,
            )
        if delay > 0:
            await asyncio.sleep(delay)
