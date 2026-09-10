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
    allow_nearby_player_lookup: bool = False,
) -> RankLookupResult:
    result.score = target_score

    async def fetch_score(index: int) -> int | None:
        item = await fetch_rank_item(game, key=key, sub_key=sub_key, index=index)
        return None if item is None else int(item.score)

    async def fetch_scores(indexes: Sequence[int]) -> list[int | None]:
        if fetch_rank_items is None:
            scores = await asyncio.gather(*(fetch_score(index) for index in indexes))
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
    result.budget_exhausted = score_range.budget_exhausted
    if score_range.last_index is None:
        return result

    search_end = score_range.last_index + 1
    result.searched_limit = min(result.searched_limit, search_end)
    if score_range.match_start is None or score_range.match_end is None:
        if allow_nearby_player_lookup:
            return await _find_rank_near_score_insertion(
                game,
                user_id=user_id,
                key=key,
                sub_key=sub_key,
                center_index=score_range.insertion_index,
                last_index=score_range.last_index,
                page_size=page_size,
                page_limit=tie_page_limit,
                parallelism=parallelism,
                result=result,
                fetch_rank_page=fetch_rank_page,
                fetch_rank_pages=fetch_rank_pages,
            )
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
                    result.observed_score = item.score
                    return result
            if len(items) < end - page_start + 1:
                break

        remaining_tie_pages -= len(starts)
        start += page_size * len(starts)

    if allow_nearby_player_lookup:
        return await _find_rank_near_score_insertion(
            game,
            user_id=user_id,
            key=key,
            sub_key=sub_key,
            center_index=score_range.match_start,
            last_index=score_range.last_index,
            page_size=page_size,
            page_limit=tie_page_limit,
            parallelism=parallelism,
            result=result,
            fetch_rank_page=fetch_rank_page,
            fetch_rank_pages=fetch_rank_pages,
        )
    return result


async def _find_rank_near_score_insertion(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    center_index: int | None,
    last_index: int,
    page_size: int,
    page_limit: int,
    parallelism: int,
    result: RankLookupResult,
    fetch_rank_page: Callable[..., Awaitable[list[Any]]],
    fetch_rank_pages: Callable[..., Awaitable[list[list[Any]]]] | None,
) -> RankLookupResult:
    """Confirm a player near a public score that outran the rank refresh."""

    if center_index is None or page_limit <= 0:
        return result
    starts = _nearby_page_starts(
        center_index=center_index,
        last_index=last_index,
        page_size=page_size,
        page_limit=page_limit,
    )
    while starts:
        batch_size = min(max(1, parallelism), len(starts))
        batch, starts = starts[:batch_size], starts[batch_size:]
        if fetch_rank_pages is None:
            pages = await asyncio.gather(
                *(
                    fetch_rank_page(
                        game,
                        key=key,
                        sub_key=sub_key,
                        start=page_start,
                        end=min(page_start + page_size - 1, last_index),
                    )
                    for page_start in batch
                )
            )
        else:
            pages = await fetch_rank_pages(
                game,
                key=key,
                sub_key=sub_key,
                starts=batch,
            )
        for page_start, items in zip(batch, pages, strict=True):
            end = min(page_start + page_size - 1, last_index)
            result.searched_limit = max(result.searched_limit, end + 1)
            for offset, item in enumerate(items[: end - page_start + 1]):
                if item.id == user_id:
                    result.rank = page_start + offset + 1
                    result.observed_score = item.score
                    return result
    return result


def _nearby_page_starts(
    *,
    center_index: int,
    last_index: int,
    page_size: int,
    page_limit: int,
) -> tuple[int, ...]:
    center = min(max(0, center_index), last_index) // page_size * page_size
    last_start = last_index // page_size * page_size
    starts: list[int] = []
    distance = 0
    while len(starts) < page_limit:
        candidates = (
            (center,)
            if distance == 0
            else (
                center - distance * page_size,
                center + distance * page_size,
            )
        )
        added = False
        for start in candidates:
            if 0 <= start <= last_start and start not in starts:
                starts.append(start)
                added = True
                if len(starts) >= page_limit:
                    break
        if (
            not added
            and center - distance * page_size < 0
            and center + distance * page_size > last_start
        ):
            break
        distance += 1
    return tuple(starts)


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
    result.scanned_count = 0
    result.scan_complete = False
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
            result.scanned_count = page_start + min(len(items), end - page_start + 1)
            for offset, item in enumerate(items[: end - page_start + 1]):
                if item.id == user_id:
                    result.rank = page_start + offset + 1
                    result.score = item.score
                    result.observed_score = item.score
                    return result
            if len(items) < end - page_start + 1:
                result.scan_complete = True
                result.searched_limit = result.scanned_count
                return result

        start += page_size * len(starts)

    result.scan_complete = True
    result.searched_limit = result.scanned_count
    return result
