# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Awaitable, Callable
from typing import Any

from ironsbot.services.seer.rank_models import RankLookupResult, RankPageResult


async def find_rank_by_cached_position(  # noqa: PLR0913
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
) -> RankLookupResult | None:
    cached_item = get_cached_rank_item(key=key, sub_key=sub_key, user_id=user_id)
    if cached_item is None:
        return None

    result.cost.anchor_page_start = (
        cached_item.rank_index // page_size * page_size
    )
    for index, start in enumerate(rank_window_page_starts(
        center_index=cached_item.rank_index,
        page_size=page_size,
    )):
        page = await fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=start + page_size - 1,
            use_cache=False,
        )
        result.queried = True
        result.cost.page_starts.append(start)
        if page.from_cache:
            result.cost.cache_page_hits += 1
        else:
            result.cost.online_page_fetches += 1
        items = page.items
        for offset, item in enumerate(items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
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
