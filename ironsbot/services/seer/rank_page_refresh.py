# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.integrations.headless_seer.activity import headless_operation
from ironsbot.integrations.headless_seer.client import get_game_client
from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.rank_page_refresh_models import (
    RankPageRefreshFailure,
    RankPageRefreshResult,
)
from ironsbot.services.seer.rank_page_refresh_selection import (
    get_rank_page_refresh_config,
    preview_rank_page_refresh_targets,
)
from ironsbot.services.seer.rank_pages import fetch_daily_rank_page

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.config.models.seer import RankPageRefreshConfig


logger = logging.getLogger(__name__)
RANK_PAGE_REFRESH_BACKOFF_SECONDS = 300.0
_rank_page_refresh_lock = asyncio.Lock()


@dataclass(slots=True)
class _RankPageRefreshRuntimeState:
    backoff_until: float = 0.0


_rank_page_refresh_state = _RankPageRefreshRuntimeState()


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


def _set_rank_page_refresh_backoff() -> None:
    _rank_page_refresh_state.backoff_until = (
        time.monotonic() + RANK_PAGE_REFRESH_BACKOFF_SECONDS
    )


def _rank_page_refresh_backoff_remaining() -> float:
    return max(_rank_page_refresh_state.backoff_until - time.monotonic(), 0.0)


async def _sleep_between_rank_page_requests(config: RankPageRefreshConfig) -> None:
    delay = config.request_interval_seconds
    if config.request_jitter_seconds > 0:
        delay += random.uniform(0, config.request_jitter_seconds)  # nosec B311
    if delay > 0:
        await asyncio.sleep(delay)


async def refresh_rank_page_cache(
    rank_keys: Sequence[str] | None = None,
) -> RankPageRefreshResult:
    if _rank_page_refresh_lock.locked():
        logger.info("rank page cache auto refresh skipped: previous run still active")
        return RankPageRefreshResult(targets=[])

    backoff_remaining = _rank_page_refresh_backoff_remaining()
    if backoff_remaining > 0:
        logger.info(
            "rank page cache auto refresh skipped: backoff %.0fs remaining",
            backoff_remaining,
        )
        return RankPageRefreshResult(targets=[])

    async with _rank_page_refresh_lock:
        return await _refresh_rank_page_cache_unlocked(rank_keys)


async def _refresh_rank_page_cache_unlocked(
    rank_keys: Sequence[str] | None = None,
) -> RankPageRefreshResult:
    refresh_config = get_rank_page_refresh_config()
    targets = preview_rank_page_refresh_targets(rank_keys)
    if refresh_config.pages_per_run_min > 0 and targets:
        lower = min(refresh_config.pages_per_run_min, len(targets))
        upper = min(refresh_config.pages_per_run, len(targets))
        target_count = random.randint(  # nosec B311
            lower,
            upper,
        )
        targets = targets[:target_count]
    result = RankPageRefreshResult(targets=targets)
    if not targets:
        return result

    game = get_game_client()
    for index, target in enumerate(targets):
        if index > 0:
            await _sleep_between_rank_page_requests(refresh_config)
        try:
            with headless_operation(
                "后台刷榜缓存",
                (
                    f"{target.rank_key} {target.start_rank}-{target.end_rank}名"
                    f"（{target.reason}）"
                ),
                source="后台刷榜缓存",
                background=True,
            ):
                await fetch_daily_rank_page(
                    game,
                    key=target.spec.key,
                    sub_key=target.spec.sub_key,
                    start=target.raw_start,
                    count=target.raw_end - target.raw_start + 1,
                    use_cache=False,
                )
        except Exception as e:  # noqa: BLE001
            result.failures.append(
                RankPageRefreshFailure(target=target, reason=str(e) or type(e).__name__)
            )
            if _is_rank_page_refresh_connection_error(e):
                _set_rank_page_refresh_backoff()
                logger.warning(
                    "rank page cache auto refresh enters backoff after failure: %s",
                    e or type(e).__name__,
                )
                break
            continue
        result.refreshed.append(target)
    return result


__all__ = ["refresh_rank_page_cache"]
