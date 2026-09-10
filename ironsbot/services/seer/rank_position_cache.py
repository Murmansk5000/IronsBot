# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.seer.rank_models import RankLookupResult, RankPageResult
from ironsbot.services.seer.rank_player_scheduler import PlayerRankPagePriority

logger = logging.getLogger(__name__)


def restore_cached_rank_after_timeout(
    result: RankLookupResult,
    cached_item: Any,
) -> RankLookupResult:
    """Keep the last observed rank visible when live confirmation times out."""

    result.rank = int(cached_item.rank_index) + 1
    result.score = int(cached_item.score)
    result.observed_score = int(cached_item.score)
    result.failure = "查询超时"
    result.fallback_cached_at = float(cached_item.fetched_at)
    return result


async def find_rank_by_cached_position(  # noqa: C901, PLR0911, PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    page_size: int,
    result: RankLookupResult,
    get_cached_rank_item: Callable[..., Any | None],
    rank_window_page_starts: Callable[..., list[int]],
    fetch_rank_page: Callable[..., Awaitable[RankPageResult]],
    fetch_rank_pages: Callable[..., Awaitable[list[RankPageResult]]] | None = None,
    anchor_only: bool = False,
    parallelism: int = 1,
    recent_cache_max_age_seconds: float = 0,
    recent_cache_anchor_timeout_seconds: float | None = None,
) -> RankLookupResult | None:
    cached_item = get_cached_rank_item(key=key, sub_key=sub_key, user_id=user_id)
    if cached_item is None:
        return None

    result.cost.anchor_page_start = (
        cached_item.rank_index // page_size * page_size
    )
    cached_at = float(getattr(cached_item, "fetched_at", 0.0))
    cache_age_seconds = max(0.0, time.time() - cached_at)
    recent_cache = (
        recent_cache_max_age_seconds > 0
        and cache_age_seconds <= recent_cache_max_age_seconds
    )
    logger.info(
        "player rank cached anchor: key=%s sub_key=%s user_id=%s rank=%s "
        "cache_age=%.3fs recent=%s",
        key,
        sub_key,
        user_id,
        cached_item.rank_index + 1,
        cache_age_seconds,
        recent_cache,
    )
    result.cost.cached_rank_age_seconds = cache_age_seconds
    result.cost.used_recent_cache_anchor = recent_cache
    starts = rank_window_page_starts(
        center_index=cached_item.rank_index,
        page_size=page_size,
    )

    async def inspect(start: int, page: RankPageResult, *, index: int) -> bool:
        result.queried = True
        result.cost.page_starts.append(start)
        if page.from_cache:
            result.cost.cache_page_hits += 1
        else:
            result.cost.online_page_fetches += 1
        for offset, item in enumerate(page.items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
                result.observed_score = item.score
                result.cost.anchor_page_hit = index == 0
                return True
        return False

    anchor_start = starts[0]
    try:
        page = await fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=anchor_start,
            end=anchor_start + page_size - 1,
            use_cache=False,
            page_phase="recent_anchor" if recent_cache else "cached_anchor",
            page_priority=(
                PlayerRankPagePriority.RECENT_CACHE_ANCHOR
                if recent_cache
                else PlayerRankPagePriority.CACHED_ANCHOR
            ),
            page_timeout_seconds=(
                recent_cache_anchor_timeout_seconds if recent_cache else None
            ),
            page_max_retries=0 if recent_cache else None,
        )
    except (
        TimeoutError,
        asyncio.TimeoutError,
        ConnectionError,
        DisconnectedError,
        NotLoggedInError,
    ):
        if not recent_cache:
            raise
        logger.info(
            "player rank recent cached anchor failed; using cache: key=%s "
            "sub_key=%s user_id=%s rank=%s cache_age=%.3fs",
            key,
            sub_key,
            user_id,
            cached_item.rank_index + 1,
            cache_age_seconds,
        )
        result.cost.used_recent_cache_fallback = True
        return restore_cached_rank_after_timeout(result, cached_item)
    if await inspect(anchor_start, page, index=0):
        return result
    if anchor_only:
        result.cost.restricted_miss = True
        return result

    remaining_starts = starts[1:]
    for offset in range(0, len(remaining_starts), max(1, parallelism)):
        batch_starts = tuple(remaining_starts[offset : offset + max(1, parallelism)])
        result.cost.expanded = True
        if fetch_rank_pages is None:
            pages = await asyncio.gather(
                *(
                    fetch_rank_page(
                        game,
                        key=key,
                        sub_key=sub_key,
                        start=start,
                        end=start + page_size - 1,
                        use_cache=False,
                        parallel=True,
                    )
                    for start in batch_starts
                )
            )
        else:
            pages = await fetch_rank_pages(
                game,
                key=key,
                sub_key=sub_key,
                starts=batch_starts,
                use_cache=False,
                page_phase="cached_window",
            )
        for index, (start, page) in enumerate(
            zip(batch_starts, pages, strict=True),
            start=offset + 1,
        ):
            if await inspect(start, page, index=index):
                return result
            if len(page.items) < page_size and start > cached_item.rank_index:
                return None

    return None
