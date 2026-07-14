# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Awaitable, Callable
from typing import Any

from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.rank_score_search import (
    DescendingScoreSearchLimits,
    locate_descending_score_range,
)


async def find_rank_by_score(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    target_score: int,
    limit: int,
    page_size: int,
    result: RankLookupResult,
    score_search_probe_limit: Callable[[int], int],
    score_search_tie_page_limit: Callable[[], int],
    fetch_rank_item: Callable[..., Awaitable[Any | None]],
    fetch_rank_page: Callable[..., Awaitable[list[Any]]],
) -> RankLookupResult:
    result.score = target_score

    async def fetch_score(index: int) -> int | None:
        item = await fetch_rank_item(game, key=key, sub_key=sub_key, index=index)
        return None if item is None else int(item.score)

    tie_page_limit = score_search_tie_page_limit()
    score_range = await locate_descending_score_range(
        0,
        limit,
        target_score,
        fetch_score,
        limits=DescendingScoreSearchLimits(
            probe_count=score_search_probe_limit(limit),
            tie_fallback_size=page_size * tie_page_limit,
        ),
    )
    if score_range.last_index is None:
        return result

    search_end = score_range.last_index + 1
    result.searched_limit = min(result.searched_limit, search_end)
    if score_range.match_start is None or score_range.match_end is None:
        return result

    tie_end = score_range.match_end
    start = score_range.match_start
    remaining_tie_pages = tie_page_limit
    while start < tie_end and remaining_tie_pages > 0:
        end = min(start + page_size - 1, tie_end - 1)
        items = await fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
        )

        for offset, item in enumerate(items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
                return result

        if len(items) < end - start + 1:
            return result

        remaining_tie_pages -= 1
        start = end + 1

    return result


async def find_rank_by_linear_scan(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    limit: int,
    page_size: int,
    result: RankLookupResult,
    fetch_rank_page: Callable[..., Awaitable[list[Any]]],
) -> RankLookupResult:
    start = 0
    while start < limit:
        end = min(start + page_size - 1, limit - 1)
        items = await fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=end,
        )

        for offset, item in enumerate(items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
                return result

        if len(items) < end - start + 1:
            return result

        start = end + 1

    return result
