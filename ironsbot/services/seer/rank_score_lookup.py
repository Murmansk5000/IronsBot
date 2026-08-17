# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from ironsbot.services.seer.rank_models import RankLookupResult
from ironsbot.services.seer.rank_score_search import (
    DescendingScoreSearchLimits,
    locate_descending_score_range,
)


async def find_rank_by_score(  # noqa: C901, PLR0913
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
    fetch_rank_items: Callable[..., Awaitable[list[Any | None]]] | None = None,
    fetch_rank_pages: Callable[..., Awaitable[list[list[Any]]]] | None = None,
    parallelism: int = 1,
) -> RankLookupResult:
    result.score = target_score

    async def fetch_score(index: int) -> int | None:
        item = await fetch_rank_item(game, key=key, sub_key=sub_key, index=index)
        return None if item is None else int(item.score)

    async def fetch_scores(indexes: Sequence[int]) -> list[int | None]:
        if fetch_rank_items is None:
            scores = await asyncio.gather(
                *(fetch_score(index) for index in indexes)
            )
            return list(scores)
        items = await fetch_rank_items(
            game,
            key=key,
            sub_key=sub_key,
            indexes=indexes,
        )
        return [None if item is None else int(item.score) for item in items]

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
        parallelism=parallelism,
        fetch_scores=fetch_scores,
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
        batch_size = min(max(1, parallelism), remaining_tie_pages)
        starts = tuple(start + page_size * offset for offset in range(batch_size))
        starts = tuple(page_start for page_start in starts if page_start < tie_end)
        if fetch_rank_pages is None:
            pages = await asyncio.gather(
                *(
                    fetch_rank_page(
                        game,
                        key=key,
                        sub_key=sub_key,
                        start=page_start,
                        end=min(page_start + page_size - 1, tie_end - 1),
                    )
                    for page_start in starts
                )
            )
        else:
            pages = await fetch_rank_pages(
                game,
                key=key,
                sub_key=sub_key,
                starts=starts,
            )

        for page_start, items in zip(starts, pages, strict=True):
            end = min(page_start + page_size - 1, tie_end - 1)
            for offset, item in enumerate(items[: end - page_start + 1]):
                if item.id == user_id:
                    result.rank = page_start + offset + 1
                    result.score = item.score
                    return result
            if len(items) < end - page_start + 1:
                return result

        remaining_tie_pages -= len(starts)
        start += page_size * len(starts)

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
    fetch_rank_pages: Callable[..., Awaitable[list[list[Any]]]] | None = None,
    parallelism: int = 1,
) -> RankLookupResult:
    start = 0
    while start < limit:
        remaining_pages = (limit - start + page_size - 1) // page_size
        batch_size = min(max(1, parallelism), remaining_pages)
        starts = tuple(start + page_size * offset for offset in range(batch_size))
        if fetch_rank_pages is None:
            pages = await asyncio.gather(
                *(
                    fetch_rank_page(
                        game,
                        key=key,
                        sub_key=sub_key,
                        start=page_start,
                        end=min(page_start + page_size - 1, limit - 1),
                    )
                    for page_start in starts
                )
            )
        else:
            pages = await fetch_rank_pages(
                game,
                key=key,
                sub_key=sub_key,
                starts=starts,
            )

        for page_start, items in zip(starts, pages, strict=True):
            end = min(page_start + page_size - 1, limit - 1)
            for offset, item in enumerate(items[: end - page_start + 1]):
                if item.id == user_id:
                    result.rank = page_start + offset + 1
                    result.score = item.score
                    return result
            if len(items) < end - page_start + 1:
                return result

        start += page_size * len(starts)

    return result
