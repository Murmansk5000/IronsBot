# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.rank_score_search_support import (
    RankScoreSegmentDependencies,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.seer.rank_models import (
        RankScoreMissProof,
        RankScoreSearchResult,
    )


@dataclass(frozen=True, slots=True)
class RankScoreServiceDependencies:
    rank_page_size: Callable[[], int]
    rank_page_start: Callable[[int], int]
    score_search_limit: Callable[[int | None], int]
    score_search_probe_limit: Callable[[int], int]
    score_search_tie_page_limit: Callable[[], int]
    get_cached_score_indexes: Callable[..., list[int]]
    get_cache_summary: Callable[..., object]
    get_cached_page_result: Callable[..., object]
    score_miss_proof_from_page: Callable[..., RankScoreMissProof | None]
    fetch_cached_candidates_impl: Callable[..., Awaitable[RankScoreSearchResult | None]]
    fetch_rank_score_segment_impl: Callable[..., Awaitable[RankScoreSearchResult]]
    cached_score_candidate_page_starts_impl: Callable[..., list[int]]
    cached_score_miss_boundary_impl: Callable[..., RankScoreMissProof | None]
    find_last_existing_score_index: Callable[
        ...,
        Awaitable[tuple[int | None, int | None]],
    ]
    fetch_rank_item: Callable[..., Awaitable[Any | None]]
    fetch_rank_page_result: Callable[..., Awaitable[Any]]


def cached_score_candidate_page_starts(  # noqa: PLR0913
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
    deps: RankScoreServiceDependencies,
) -> list[int]:
    return deps.cached_score_candidate_page_starts_impl(
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_page_start=deps.rank_page_start,
        get_cached_score_indexes=deps.get_cached_score_indexes,
        get_cache_summary=deps.get_cache_summary,
    )


def cached_score_miss_boundary(  # noqa: PLR0913
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
    rank_offset: int,
    deps: RankScoreServiceDependencies,
) -> RankScoreMissProof | None:
    return deps.cached_score_miss_boundary_impl(
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
        get_cache_summary=deps.get_cache_summary,
        get_cached_score_indexes=deps.get_cached_score_indexes,
        get_cached_page_result=deps.get_cached_page_result,
        score_miss_proof_from_page=deps.score_miss_proof_from_page,
    )


async def fetch_rank_score_segment_from_cached_candidates(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
    rank_offset: int,
    result: RankScoreSearchResult,
    candidate_starts: list[int],
    deps: RankScoreServiceDependencies,
) -> RankScoreSearchResult | None:
    return await deps.fetch_cached_candidates_impl(
        game,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
        result=result,
        candidate_starts=candidate_starts,
        rank_page_size=deps.rank_page_size,
        rank_page_start=deps.rank_page_start,
        score_search_tie_page_limit=deps.score_search_tie_page_limit,
        fetch_rank_page_result=deps.fetch_rank_page_result,
    )


async def fetch_rank_score_segment(  # noqa: PLR0913
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
    deps: RankScoreServiceDependencies,
) -> RankScoreSearchResult:
    segment_deps = RankScoreSegmentDependencies(
        score_search_limit=deps.score_search_limit,
        rank_page_size=deps.rank_page_size,
        rank_page_start=deps.rank_page_start,
        cached_score_miss_boundary=lambda **kwargs: cached_score_miss_boundary(
            **kwargs,
            deps=deps,
        ),
        cached_score_candidate_page_starts=lambda **kwargs: (
            cached_score_candidate_page_starts(**kwargs, deps=deps)
        ),
        fetch_cached_candidates=lambda *args, **kwargs: (
            fetch_rank_score_segment_from_cached_candidates(
                *args,
                **kwargs,
                deps=deps,
            )
        ),
        score_search_probe_limit=deps.score_search_probe_limit,
        score_search_tie_page_limit=deps.score_search_tie_page_limit,
        find_last_existing_score_index=deps.find_last_existing_score_index,
        fetch_rank_item=deps.fetch_rank_item,
        fetch_rank_page_result=deps.fetch_rank_page_result,
        score_miss_proof_from_page=deps.score_miss_proof_from_page,
    )
    return await deps.fetch_rank_score_segment_impl(
        game,
        key=key,
        sub_key=sub_key,
        title=title,
        score_name=score_name,
        target_score=target_score,
        search_limit=search_limit,
        start_index=start_index,
        rank_offset=rank_offset,
        deps=segment_deps,
    )


__all__ = [
    "RankScoreServiceDependencies",
    "cached_score_candidate_page_starts",
    "cached_score_miss_boundary",
    "fetch_rank_score_segment",
    "fetch_rank_score_segment_from_cached_candidates",
]
