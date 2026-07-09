# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Awaitable, Callable
from typing import Any

from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.rank_score_search_support import (
    RankSearchBudgetExhaustedError,
)


async def find_rank_by_score(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915
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
    find_last_existing_score_index: Callable[
        [int, int, Callable[[int], Awaitable[int | None]]],
        Awaitable[tuple[int | None, int | None]],
    ],
    fetch_rank_item: Callable[..., Awaitable[Any | None]],
    fetch_rank_page: Callable[..., Awaitable[list[Any]]],
) -> RankLookupResult:
    result.score = target_score
    remaining_probes = score_search_probe_limit(limit)
    item_cache: dict[int, Any | None] = {}

    async def item_at(index: int) -> Any | None:
        nonlocal remaining_probes

        if index in item_cache:
            return item_cache[index]

        if remaining_probes <= 0:
            raise RankSearchBudgetExhaustedError

        remaining_probes -= 1
        item = await fetch_rank_item(game, key=key, sub_key=sub_key, index=index)
        item_cache[index] = item
        return item

    async def score_at(index: int) -> int | None:
        item = await item_at(index)
        return None if item is None else item.score

    try:
        last_index, boundary_score = await find_last_existing_score_index(
            0,
            limit,
            score_at,
        )
    except RankSearchBudgetExhaustedError:
        return result

    if last_index is None:
        return result

    search_end = last_index + 1
    result.searched_limit = min(result.searched_limit, search_end)
    if boundary_score is None or target_score < boundary_score:
        return result

    low = 0
    high = search_end
    try:
        while low < high:
            mid = (low + high) // 2
            score = await score_at(mid)
            if score is None or score <= target_score:
                high = mid
            else:
                low = mid + 1
    except RankSearchBudgetExhaustedError:
        return result

    first_same_or_lower = low
    if first_same_or_lower >= search_end:
        return result

    try:
        first_score = await score_at(first_same_or_lower)
    except RankSearchBudgetExhaustedError:
        return result
    if first_score != target_score:
        return result

    low = first_same_or_lower
    high = search_end
    tie_end = search_end
    try:
        while low < high:
            mid = (low + high) // 2
            score = await score_at(mid)
            if score is None or score < target_score:
                high = mid
            else:
                low = mid + 1
        tie_end = low
    except RankSearchBudgetExhaustedError:
        tie_end = min(
            search_end,
            first_same_or_lower + page_size * score_search_tie_page_limit(),
        )

    tie_end = min(tie_end, search_end)
    start = first_same_or_lower
    remaining_tie_pages = score_search_tie_page_limit()
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
