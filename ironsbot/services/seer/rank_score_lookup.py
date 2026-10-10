# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Awaitable, Callable
from typing import Any

from ironsbot.services.seer.rank_models import RankLookupResult, RankPageResult
from ironsbot.services.seer.rank_page_batches import (
    RankProbePages,
    ordered_page_batches,
)
from ironsbot.services.seer.rank_pagination import (
    RankPageConflictError,
    RankPageSequence,
    rank_window_page_starts,
)
from ironsbot.services.seer.rank_score_helpers import validate_score_sample
from ironsbot.services.seer.rank_score_search import (
    DescendingScoreSearchLimits,
    locate_descending_score_range,
)


async def find_rank_by_score(  # noqa: C901, PLR0913 - bounded probes and tie scan outcomes
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
    fetch_rank_page: Callable[..., Awaitable[RankPageResult]],
    parallelism: Callable[[], int] | None = None,
    allow_nearby_player_lookup: bool = False,
) -> RankLookupResult:
    result.score = target_score

    async def fetch_probe(start: int) -> RankPageResult:
        page = await fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=start + page_size - 1,
        )
        result.record_page(start, page)
        return page

    probe_pages = RankProbePages(fetch_probe)

    async def fetch_score(index: int) -> int | None:
        start = index // page_size * page_size
        page = await probe_pages(start)
        offset = index - start
        item = page.items[offset] if offset < len(page.items) else None
        return None if item is None else int(item.score)

    tie_page_limit = score_search_tie_page_limit()
    try:
        score_range = await locate_descending_score_range(
            0,
            limit,
            target_score,
            fetch_score,
            parallelism=parallelism,
            limits=DescendingScoreSearchLimits(
                probe_count=score_search_probe_limit(limit),
                tie_fallback_size=page_size * tie_page_limit,
            ),
        )
    except RankPageConflictError as error:
        result.failure = str(error)
        return result
    if score_range.budget_exhausted:
        result.failure = "已达二分探针上限，排名尚未确认"
    if score_range.last_index is None:
        return result

    search_end = score_range.last_index + 1
    result.searched_limit = min(result.searched_limit, search_end)
    if score_range.match_start is None or score_range.match_end is None:
        if allow_nearby_player_lookup:
            result = await _find_rank_near_score_insertion(
                game,
                user_id=user_id,
                key=key,
                sub_key=sub_key,
                center_index=(
                    score_range.insertion_index
                    if score_range.insertion_index is not None
                    else score_range.last_index
                ),
                last_index=score_range.last_index,
                page_size=page_size,
                page_limit=tie_page_limit,
                result=result,
                fetch_rank_page=fetch_rank_page,
                parallelism=parallelism,
            )
        return result

    tie_end = score_range.match_end
    start = score_range.match_start
    next_start = start
    remaining_tie_pages = tie_page_limit
    sequence = RankPageSequence()

    async def fetch_tie_page(start: int) -> RankPageResult:
        return await fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=min(start + page_size - 1, tie_end - 1),
        )

    starts = range(
        start, min(tie_end, start + remaining_tie_pages * page_size), page_size
    )
    async for start, page in ordered_page_batches(
        starts, fetch_tie_page, parallelism, phase="score_tie"
    ):
        end = min(start + page_size - 1, tie_end - 1)
        result.record_page(start, page)
        items = page.items
        try:
            validate_score_sample(
                page,
                start=start,
                end=end,
                target_score=target_score,
                score_range=score_range,
                sequence=sequence,
            )
        except RankPageConflictError as error:
            result.failure = str(error)
            return result

        for offset, item in enumerate(items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
                result.observed_score = item.score
                result.failure = None
                return result

        if len(items) < end - start + 1:
            break

        remaining_tie_pages -= 1
        next_start = end + 1

    if next_start < tie_end or score_range.truncated:
        result.failure = "已达同分段查找上限，排名尚未确认"
    if allow_nearby_player_lookup:
        result = await _find_rank_near_score_insertion(
            game,
            user_id=user_id,
            key=key,
            sub_key=sub_key,
            center_index=score_range.match_start,
            last_index=score_range.last_index,
            page_size=page_size,
            page_limit=tie_page_limit,
            result=result,
            fetch_rank_page=fetch_rank_page,
            parallelism=parallelism,
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
    result: RankLookupResult,
    fetch_rank_page: Callable[..., Awaitable[RankPageResult]],
    parallelism: Callable[[], int] | None,
) -> RankLookupResult:
    if center_index is None or page_limit <= 0:
        return result
    starts = tuple(
        start
        for start in rank_window_page_starts(
            center_index=min(center_index, last_index),
            page_size=page_size,
            window_pages=page_limit,
        )
        if start <= last_index
    )[:page_limit]

    async def fetch(start: int) -> RankPageResult:
        return await fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=min(start + page_size - 1, last_index),
        )

    observed_pages: dict[int, RankPageResult] = {}
    async for start, page in ordered_page_batches(
        starts, fetch, parallelism, phase="score_nearby"
    ):
        result.record_page(start, page)
        end = min(start + page_size - 1, last_index)
        if len(page.items) != end - start + 1:
            result.failure = str(RankPageConflictError())
            return result
        observed_pages[start] = page
        sequence = RankPageSequence()
        try:
            for observed_start in sorted(observed_pages):
                sequence.include(
                    (int(item.id), int(item.score))
                    for item in observed_pages[observed_start].items
                )
        except RankPageConflictError as error:
            result.failure = str(error)
            return result
        for offset, item in enumerate(page.items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = int(item.score)
                result.observed_score = result.score
                result.failure = None
                return result
    if result.failure is None:
        result.failure = "已检查分数附近的榜单，排名尚未确认"
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
    fetch_rank_page: Callable[..., Awaitable[RankPageResult]],
    parallelism: Callable[[], int] | None = None,
    ascending: bool = False,
) -> RankLookupResult:
    start = 0
    sequence = RankPageSequence(ascending=ascending)

    async def fetch(start: int) -> RankPageResult:
        return await fetch_rank_page(
            game,
            key=key,
            sub_key=sub_key,
            start=start,
            end=min(start + page_size - 1, limit - 1),
        )

    async for start, page in ordered_page_batches(
        range(0, limit, page_size), fetch, parallelism, phase="linear_scan"
    ):
        end = min(start + page_size - 1, limit - 1)
        result.record_page(start, page)
        items = page.items

        try:
            sequence.include((int(item.id), int(item.score)) for item in items)
        except RankPageConflictError as error:
            result.failure = str(error)
            return result

        for offset, item in enumerate(items):
            if item.id == user_id:
                result.rank = start + offset + 1
                result.score = item.score
                result.observed_score = item.score
                return result

        if len(items) < end - start + 1:
            return result

    return result
