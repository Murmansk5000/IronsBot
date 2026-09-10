# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import time
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.rank_models import (
    RankScoreSearchItem,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_score_cache import (
    cached_score_candidate_page_starts,
    fetch_rank_score_segment_from_cached_candidates,
)
from ironsbot.services.seer.rank_score_helpers import (
    score_miss_proof_from_page,
    score_segment_sample_indexes,
)
from ironsbot.services.seer.rank_score_search import (
    DescendingScoreSearchLimits,
    locate_descending_score_range,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ironsbot.services.seer.rank_models import RankPageResult, RankScoreMissProof


@dataclass(frozen=True, slots=True)
class RankScoreSegmentDependencies:
    score_search_limit: Callable[[int | None], int]
    rank_page_size: Callable[[], int]
    rank_page_start: Callable[[int], int]
    cached_score_candidate_page_starts: Callable[..., list[int]]
    fetch_cached_candidates: Callable[..., Awaitable[RankScoreSearchResult | None]]
    score_search_probe_limit: Callable[[int], int]
    score_search_tie_page_limit: Callable[[], int]
    fetch_rank_item: Callable[..., Awaitable[Any | None]]
    fetch_rank_items: Callable[..., Awaitable[list[Any | None]]] | None
    fetch_rank_page_result: Callable[..., Awaitable[RankPageResult]]
    fetch_rank_page_results: (
        Callable[..., Awaitable[list[RankPageResult]]] | None
    )
    score_miss_proof_from_page: Callable[..., RankScoreMissProof | None]
    parallelism: int = 1


def build_rank_score_segment_dependencies(
    service: Any,
    game: Any,
    *,
    rank_key: str | None,
    use_superuser_limit: bool,
) -> RankScoreSegmentDependencies:
    parallelism = service.rank_probe_parallelism(game)
    batch_enabled = parallelism > 1
    return RankScoreSegmentDependencies(
        score_search_limit=partial(
            service._score_search_limit,
            rank_key,
            use_superuser_limit=use_superuser_limit,
        ),
        rank_page_size=service.page_size,
        rank_page_start=service.page_start,
        cached_score_candidate_page_starts=partial(
            cached_score_candidate_page_starts,
            rank_page_start=service.page_start,
            get_cached_score_indexes=service.cache.score_indexes,
            get_cache_summary=service.cache.summary,
        ),
        fetch_cached_candidates=partial(
            fetch_rank_score_segment_from_cached_candidates,
            rank_page_size=service.page_size,
            rank_page_start=service.page_start,
            score_search_tie_page_limit=service._tie_page_limit,
            fetch_rank_page_result=service.fetch_page_result,
        ),
        score_search_probe_limit=service._probe_limit,
        score_search_tie_page_limit=service._tie_page_limit,
        fetch_rank_item=service.fetch_item,
        fetch_rank_items=service.fetch_item_batch if batch_enabled else None,
        fetch_rank_page_result=service.fetch_page_result,
        fetch_rank_page_results=service.fetch_page_batch if batch_enabled else None,
        score_miss_proof_from_page=score_miss_proof_from_page,
        parallelism=parallelism,
    )


async def fetch_score_segment_for_service(  # noqa: PLR0913
    service: Any,
    game: Any,
    *,
    rank_key: str | None,
    key: int,
    sub_key: int,
    title: str,
    score_name: str,
    target_score: int,
    search_limit: int | None,
    start_index: int,
    sample_limit: int | None,
    use_superuser_limit: bool,
) -> RankScoreSearchResult:
    if rank_key is not None and service.exclusion_policy.excluded_user_ids(rank_key):
        from ironsbot.services.seer.rank_exclusion_lookups import (
            fetch_visible_score_segment,
        )

        return await fetch_visible_score_segment(
            service,
            game,
            rank_key=rank_key,
            key=key,
            sub_key=sub_key,
            title=title,
            score_name=score_name,
            target_score=target_score,
            search_limit=search_limit,
            use_superuser_limit=use_superuser_limit,
        )
    return await fetch_rank_score_segment(
        game,
        key=key,
        sub_key=sub_key,
        title=title,
        score_name=score_name,
        target_score=target_score,
        search_limit=search_limit,
        start_index=start_index,
        sample_limit=sample_limit,
        deps=build_rank_score_segment_dependencies(
            service,
            game,
            rank_key=rank_key,
            use_superuser_limit=use_superuser_limit,
        ),
    )


async def _populate_score_miss_proof_from_online_page(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    target_score: int,
    gap_index: int,
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
        fetched_at=fetched_at,
    )
    if proof is None:
        return
    result.boundary_score = proof.boundary_score
    result.fetched_at = proof.fetched_at
    result.higher_gap = proof.higher_gap
    result.lower_gap = proof.lower_gap


async def fetch_rank_score_segment(  # noqa: C901, PLR0912, PLR0913, PLR0915
    game: Any,
    *,
    key: int,
    sub_key: int,
    title: str,
    score_name: str,
    target_score: int,
    search_limit: int | None = None,
    start_index: int = 0,
    sample_limit: int | None = None,
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
    cached_result = await deps.fetch_cached_candidates(
        game,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        result=result,
        sample_limit=sample_limit,
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

    async def fetch_scores(indexes: Sequence[int]) -> list[int | None]:
        if deps.fetch_rank_items is None:
            return [await fetch_score(index) for index in indexes]
        items = await deps.fetch_rank_items(
            game,
            key=key,
            sub_key=sub_key,
            indexes=indexes,
            use_cache=False,
        )
        return [None if item is None else int(item.score) for item in items]

    score_range = await locate_descending_score_range(
        start_index,
        end_index,
        target_score,
        fetch_score,
        limits=DescendingScoreSearchLimits(
            probe_count=deps.score_search_probe_limit(limit),
            tie_fallback_size=page_size * deps.score_search_tie_page_limit(),
        ),
        parallelism=deps.parallelism,
        fetch_scores=fetch_scores,
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
            result=result,
            deps=deps,
        )
        return result

    first_same_or_lower = score_range.match_start
    tie_end = score_range.match_end
    result.truncated = score_range.truncated
    result.start_rank = first_same_or_lower + 1
    result.end_rank = tie_end
    result.total_count = max(0, tie_end - first_same_or_lower)

    sample_indexes = score_segment_sample_indexes(
        first_same_or_lower,
        tie_end,
        sample_limit,
    )
    if sample_indexes is None:
        first_page_start = deps.rank_page_start(first_same_or_lower)
        last_page_start = deps.rank_page_start(max(first_same_or_lower, tie_end - 1))
        page_starts = range(first_page_start, last_page_start + 1, page_size)
    else:
        page_starts = sorted(
            {deps.rank_page_start(index) for index in sample_indexes}
        )

    max_pages = deps.score_search_tie_page_limit()
    fetched_pages = 0
    fetched_times: list[float] = []

    ordered_starts = tuple(page_starts)
    for offset in range(0, len(ordered_starts), max(1, deps.parallelism)):
        if sample_indexes is None and fetched_pages >= max_pages:
            result.truncated = True
            break
        starts = ordered_starts[offset : offset + max(1, deps.parallelism)]
        if sample_indexes is None:
            starts = starts[: max_pages - fetched_pages]
        if deps.fetch_rank_page_results is None:
            page_results = [
                await deps.fetch_rank_page_result(
                    game,
                    key=key,
                    sub_key=sub_key,
                    start=page_start,
                    end=page_start + page_size - 1,
                    use_cache=False,
                )
                for page_start in starts
            ]
        else:
            page_results = await deps.fetch_rank_page_results(
                game,
                key=key,
                sub_key=sub_key,
                starts=starts,
                use_cache=False,
            )

        short_page = False
        for page_start, page_result in zip(starts, page_results, strict=True):
            fetched_times.append(page_result.fetched_at)
            fetched_pages += 1

            for item_offset, item in enumerate(page_result.items):
                rank_index = page_start + item_offset
                if rank_index < first_same_or_lower or rank_index >= tie_end:
                    continue
                if sample_indexes is not None and rank_index not in sample_indexes:
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
            short_page = short_page or len(page_result.items) < page_size
        if short_page:
            break

    result.items.sort(key=lambda item: item.rank_index)
    result.scanned_count = len(result.items)
    result.fetched_at = max(fetched_times, default=time.time())
    return result
