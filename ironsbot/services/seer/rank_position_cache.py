# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ironsbot.core.rank_lookup_context import RankPagePolicy, rank_page_policy
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.seer.rank_models import RankLookupResult, RankPageResult
from ironsbot.services.seer.rank_page_batches import ordered_page_batches

_LOGGER = logging.getLogger(__name__)


def _record_cached_match(
    result: RankLookupResult,
    page: RankPageResult,
    user_id: int,
    start: int,
) -> bool:
    for offset, item in enumerate(page.items):
        if item.id == user_id:
            result.rank = start + offset + 1
            result.score = item.score
            return True
    return False


def restore_cached_rank_after_timeout(
    result: RankLookupResult,
    cached_item: Any,
) -> RankLookupResult:
    """Keep the last observed rank visible when live confirmation times out."""

    result.rank = int(cached_item.rank_index) + 1
    result.score = int(cached_item.score)
    result.failure = "查询超时"
    result.fallback_cached_at = float(cached_item.fetched_at)
    result.fetched_at = result.fallback_cached_at
    return result


async def find_rank_by_cached_position(  # noqa: C901, PLR0913 - anchor fallback and neighbor outcomes
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
    anchor_only: bool = False,
    recent_cache_max_age_seconds: float = 600,
    recent_cache_anchor_timeout_seconds: float = 5,
    parallelism: Callable[[], int] | None = None,
) -> RankLookupResult | None:
    cached_item = get_cached_rank_item(key=key, sub_key=sub_key, user_id=user_id)
    if cached_item is None:
        return None

    result.cost.anchor_page_start = cached_item.rank_index // page_size * page_size
    age = max(0, time.time() - float(cached_item.fetched_at))
    recent = recent_cache_max_age_seconds > 0 and age <= recent_cache_max_age_seconds
    _LOGGER.info(
        "rank cached position: key=%s rank=%s age=%.3f recent=%s",
        key,
        cached_item.rank_index + 1,
        age,
        recent,
    )
    starts = rank_window_page_starts(
        center_index=cached_item.rank_index,
        page_size=page_size,
    )

    async def fetch(start: int) -> RankPageResult:
        return await fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=start + page_size - 1,
            use_cache=False,
        )

    neighbors = ordered_page_batches(
        starts[1:],
        fetch,
        parallelism,
        phase="cached_window",
    )
    for index, start in enumerate(starts):
        quick = recent and index == 0
        policy = (
            RankPagePolicy("recent_anchor", 0, recent_cache_anchor_timeout_seconds, 0)
            if quick
            else RankPagePolicy("cached_window")
        )
        token = rank_page_policy.set(policy)
        try:
            async with asyncio.timeout(
                recent_cache_anchor_timeout_seconds if quick else None
            ):
                if index == 0:
                    page = await fetch(start)
                else:
                    _, page = await anext(neighbors)
        except (TimeoutError, ConnectionError, DisconnectedError, NotLoggedInError):
            if not quick:
                raise
            _LOGGER.info(
                "rank recent anchor failed; retaining cache: key=%s page=%s age=%.3f",
                key,
                start,
                age,
            )
            return restore_cached_rank_after_timeout(result, cached_item)
        finally:
            rank_page_policy.reset(token)
        result.record_page(start, page)
        items = page.items
        if _record_cached_match(result, page, user_id, start):
            result.cost.anchor_page_hit = index == 0
            return result

        if anchor_only:
            result.cost.restricted_miss = True
            return result
        if index > 0:
            result.cost.expanded = True
        if len(items) < page_size and start > cached_item.rank_index:
            break

    return None
