# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.rank_models import (
    RankScoreSearchItem,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_score_search import (
    DescendingScoreSearchLimits,
    locate_descending_score_range,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.seer.rank_models import RankPageResult, RankScoreMissProof


@dataclass(frozen=True, slots=True)
class RankScoreSegmentDependencies:
    score_search_limit: Callable[[int | None], int]
    rank_page_size: Callable[[], int]
    rank_page_start: Callable[[int], int]
    cached_score_miss_boundary: Callable[..., RankScoreMissProof | None]
    cached_score_candidate_page_starts: Callable[..., list[int]]
    fetch_cached_candidates: Callable[..., Awaitable[RankScoreSearchResult | None]]
    score_search_probe_limit: Callable[[int], int]
    score_search_tie_page_limit: Callable[[], int]
    fetch_rank_item: Callable[..., Awaitable[Any | None]]
    fetch_rank_page_result: Callable[..., Awaitable[RankPageResult]]
    score_miss_proof_from_page: Callable[..., RankScoreMissProof | None]


async def _populate_score_miss_proof_from_online_page(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    target_score: int,
    gap_index: int,
    rank_offset: int,
    result: RankScoreSearchResult,
    deps: RankScoreSegmentDependencies,
) -> None:
    page_size = deps.rank_page_size()
    page_start = deps.rank_page_start(gap_index)
    proof_page_start = page_start
    page_result = await deps.fetch_rank_page_result(
        game,
        key=key,
        sub_key=sub_key,
        start=page_start,
        end=page_start + page_size - 1,
        use_cache=False,
    )
    proof_items = page_result.items
    fetched_at = page_result.fetched_at
    if page_start > 0 and gap_index == page_start:
        previous_page_start = page_start - page_size
        previous_page_result = await deps.fetch_rank_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=previous_page_start,
            end=previous_page_start + page_size - 1,
            use_cache=False,
        )
        proof_page_start = previous_page_start
        proof_items = [*previous_page_result.items, *page_result.items]
        fetched_at = max(previous_page_result.fetched_at, page_result.fetched_at)
    proof = deps.score_miss_proof_from_page(
        items=proof_items,
        page_start=proof_page_start,
        target_score=target_score,
        rank_offset=rank_offset,
        fetched_at=fetched_at,
    )
    if proof is None:
        return
    result.boundary_score = proof.boundary_score
    result.fetched_at = proof.fetched_at
    result.higher_gap = proof.higher_gap
    result.lower_gap = proof.lower_gap


async def fetch_rank_score_segment(  # noqa: C901, PLR0911, PLR0913, PLR0915
    game: Any,
    *,
    key: int,
    sub_key: int,
    title: str,
    score_name: str,
    target_score: int,
    search_limit: int | None = None,
    start_index: int = 0,
    rank_offset: int = 0,
    deps: RankScoreSegmentDependencies,
) -> RankScoreSearchResult:
    limit = deps.score_search_limit(search_limit)
    result = RankScoreSearchResult(
        title=title,
        score_name=score_name,
        target_score=target_score,
        searched_limit=limit,
        queried=limit > 0,
    )
    if target_score <= 0 or limit <= 0:
        return result

    start_index = max(0, start_index)
    end_index = start_index + limit
    page_size = deps.rank_page_size()
    cached_miss = deps.cached_score_miss_boundary(
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
    )
    if cached_miss is not None:
        result.boundary_score = cached_miss.boundary_score
        result.fetched_at = cached_miss.fetched_at
        result.higher_gap = cached_miss.higher_gap
        result.lower_gap = cached_miss.lower_gap
        return result

    cached_result = await deps.fetch_cached_candidates(
        game,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
        result=result,
        candidate_starts=deps.cached_score_candidate_page_starts(
            key=key,
            sub_key=sub_key,
            target_score=target_score,
            start_index=start_index,
            end_index=end_index,
        ),
    )
    if cached_result is not None:
        return cached_result

    async def fetch_score(index: int) -> int | None:
        item = await deps.fetch_rank_item(
            game,
            key=key,
            sub_key=sub_key,
            index=index,
            use_cache=False,
        )
        return None if item is None else int(item.score)

    score_range = await locate_descending_score_range(
        start_index,
        end_index,
        target_score,
        fetch_score,
        limits=DescendingScoreSearchLimits(
            probe_count=deps.score_search_probe_limit(limit),
            tie_fallback_size=page_size * deps.score_search_tie_page_limit(),
        ),
    )
    result.boundary_score = score_range.boundary_score
    if score_range.last_index is None:
        return result

    end_index = score_range.last_index + 1
    result.searched_limit = min(result.searched_limit, end_index - start_index)
    if score_range.match_start is None or score_range.match_end is None:
        if score_range.insertion_index is None or score_range.budget_exhausted:
            return result
        await _populate_score_miss_proof_from_online_page(
            game,
            key=key,
            sub_key=sub_key,
            target_score=target_score,
            gap_index=score_range.insertion_index,
            rank_offset=rank_offset,
            result=result,
            deps=deps,
        )
        return result

    first_same_or_lower = score_range.match_start
    tie_end = score_range.match_end
    result.truncated = score_range.truncated
    result.start_rank = first_same_or_lower + 1 + rank_offset
    result.end_rank = tie_end + rank_offset
    result.total_count = max(0, tie_end - first_same_or_lower)

    first_page_start = deps.rank_page_start(first_same_or_lower)
    last_page_start = deps.rank_page_start(max(first_same_or_lower, tie_end - 1))
    max_pages = deps.score_search_tie_page_limit()
    fetched_pages = 0
    fetched_times: list[float] = []

    for page_start in range(first_page_start, last_page_start + 1, page_size):
        if fetched_pages >= max_pages:
            result.truncated = True
            break

        page_result = await deps.fetch_rank_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=page_start,
            end=page_start + page_size - 1,
            use_cache=False,
        )
        fetched_times.append(page_result.fetched_at)
        fetched_pages += 1

        for offset, item in enumerate(page_result.items):
            rank_index = page_start + offset
            if rank_index < first_same_or_lower or rank_index >= tie_end:
                continue
            if int(item.score) != target_score:
                continue
            result.items.append(
                RankScoreSearchItem(
                    id=int(item.id),
                    nick=str(item.nick),
                    score=int(item.score),
                    rank_index=rank_index,
                )
            )

        if len(page_result.items) < page_size:
            break

    result.scanned_count = len(result.items)
    result.fetched_at = max(fetched_times, default=time.time())
    return result
