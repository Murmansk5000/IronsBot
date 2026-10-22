# SPDX-License-Identifier: GPL-3.0-or-later
"""Cache-only leaderboard queries used when foreground quota is exhausted."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.rank_models import (
    RankLookupCost,
    RankLookupResult,
    RankPageResult,
    RankScoreSearchItem,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_score_cache import (
    cached_score_candidate_page_starts,
)
from ironsbot.services.seer.rank_score_helpers import (
    score_miss_proof_from_page,
    score_segment_coverage,
)
from ironsbot.services.seer.rank_visibility import EXCLUSION_PREFIX_SIZE

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from ironsbot.services.seer.rank_page_cache_models import CachedRankLookup


def fetch_cached_score_segment(  # noqa: C901, PLR0911, PLR0912, PLR0913
    cache: Any,
    *,
    key: int,
    sub_key: int,
    title: str,
    score_name: str,
    target_score: int,
    search_limit: int,
    start_index: int,
    sample_limit: int | None,
    page_size: int,
    page_start: Callable[[int], int],
    tie_page_limit: int,
    excluded_user_ids: Collection[int],
) -> RankScoreSearchResult | None:
    """Return a proved score segment from complete cached pages only."""

    if target_score <= 0 or search_limit <= 0 or tie_page_limit <= 0:
        return None
    start_index = max(0, start_index)
    end_index = start_index + search_limit
    candidate_starts = cached_score_candidate_page_starts(
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_page_start=page_start,
        get_cached_score_indexes=cache.score_indexes,
        get_cache_summary=cache.summary,
    )
    if not candidate_starts:
        return None

    pages: dict[int, RankPageResult] = {}

    def read_page(page_index: int) -> RankPageResult | None:
        aligned = page_start(page_index)
        if aligned < page_start(start_index) or aligned >= end_index:
            return None
        if aligned not in pages:
            cached = _cached_page(
                cache,
                key=key,
                sub_key=sub_key,
                start=aligned,
                page_size=page_size,
            )
            if cached is None:
                return None
            pages[aligned] = cached
        return pages[aligned]

    first_page = read_page(candidate_starts[0])
    if first_page is None:
        return None

    if not any(int(item.score) == target_score for item in first_page.items):
        # The cached score boundaries are raw-server positions.  With hidden
        # users, a missing score cannot safely prove the public visible range.
        if excluded_user_ids:
            return None
        proof = score_miss_proof_from_page(
            items=first_page.items,
            page_start=page_start(candidate_starts[0]),
            target_score=target_score,
            fetched_at=first_page.fetched_at,
        )
        if proof is None:
            return None
        return RankScoreSearchResult(
            title=title,
            score_name=score_name,
            target_score=target_score,
            searched_limit=search_limit,
            queried=True,
            boundary_score=proof.boundary_score,
            fetched_at=proof.fetched_at,
            higher_gap=proof.higher_gap,
            lower_gap=proof.lower_gap,
        )

    while True:
        coverage = score_segment_coverage(
            pages,
            start_index=start_index,
            end_index=end_index,
            page_size=page_size,
            target_score=target_score,
        )
        if coverage is None:
            return None
        if not coverage.missing_pages:
            break
        for missing_start in coverage.missing_pages:
            if len(pages) >= tie_page_limit or read_page(missing_start) is None:
                return None

    matches = list(coverage.matches)
    visible_indexes = _visible_match_indexes(
        pages,
        matches=matches,
        excluded_user_ids=excluded_user_ids,
        page_size=page_size,
        page_start=page_start,
        read_page=read_page,
    )
    if visible_indexes is None:
        return None
    if not visible_indexes:
        return RankScoreSearchResult(
            title=title,
            score_name=score_name,
            target_score=target_score,
            searched_limit=search_limit,
            queried=True,
            fetched_at=min(page.fetched_at for page in pages.values()),
        )
    selected_indexes = _selected_match_indexes(
        visible_indexes,
        sample_limit=sample_limit,
    )
    visible_rank_indexes = _visible_rank_indexes(
        pages,
        excluded_user_ids=excluded_user_ids,
    )
    items = [
        RankScoreSearchItem(
            id=int(item.id),
            nick=str(item.nick),
            score=int(item.score),
            rank_index=visible_rank_indexes[index],
        )
        for page_index, page in sorted(pages.items())
        for offset, item in enumerate(page.items)
        for index in (page_index + offset,)
        if index in selected_indexes
        and int(item.score) == target_score
        and index in visible_rank_indexes
    ]
    return RankScoreSearchResult(
        title=title,
        score_name=score_name,
        target_score=target_score,
        searched_limit=search_limit,
        queried=True,
        start_rank=visible_rank_indexes[visible_indexes[0]] + 1,
        end_rank=visible_rank_indexes[visible_indexes[-1]] + 1,
        total_count=len(visible_indexes),
        scanned_count=len(items),
        fetched_at=min(page.fetched_at for page in pages.values()),
        items=items,
    )


def cached_player_lookup(  # noqa: PLR0913
    cache: Any,
    *,
    key: int,
    sub_key: int,
    user_id: int,
    title: str,
    score_name: str,
    search_limit: int,
    allow_stale: bool = True,
) -> tuple[CachedRankLookup | None, RankLookupResult] | None:
    """Return a cached player fact or a cached complete miss proof."""

    cached = cache.item(
        key=key,
        sub_key=sub_key,
        user_id=user_id,
        allow_stale=allow_stale,
    )
    if cached is not None:
        return cached, RankLookupResult(
            title=title,
            score_name=score_name,
            rank=int(cached.rank_index) + 1,
            score=int(cached.score),
            fetched_at=cached.fetched_at,
            searched_limit=search_limit,
            queried=True,
            cost=RankLookupCost(cache_page_hits=1),
        )
    miss = cache.miss(
        key=key,
        sub_key=sub_key,
        user_id=user_id,
        minimum_limit=search_limit,
        allow_stale=True,
    )
    if miss is None:
        return None
    return None, RankLookupResult(
        title=title,
        score_name=score_name,
        searched_limit=int(miss.searched_limit),
        fetched_at=miss.fetched_at,
        queried=True,
        cost=RankLookupCost(cache_page_hits=1),
    )


def _cached_page(
    cache: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    page_size: int,
) -> RankPageResult | None:
    cached = cache.page(
        key=key,
        sub_key=sub_key,
        start=start,
        end=start + page_size - 1,
        allow_stale=False,
    )
    if cached is None:
        return None
    return RankPageResult(
        items=list(cached.items),
        fetched_at=float(cached.fetched_at),
        from_cache=True,
    )


def _visible_match_indexes(  # noqa: PLR0913
    pages: dict[int, RankPageResult],
    *,
    matches: list[int],
    excluded_user_ids: Collection[int],
    page_size: int,
    page_start: Callable[[int], int],
    read_page: Callable[[int], RankPageResult | None],
) -> list[int] | None:
    if not excluded_user_ids:
        return matches
    last_page_start = page_start(min(matches[-1], EXCLUSION_PREFIX_SIZE - 1))
    for current_start in range(0, last_page_start + 1, page_size):
        if read_page(current_start) is None:
            return None
    return [
        index
        for index in matches
        if index >= EXCLUSION_PREFIX_SIZE
        or int(pages[page_start(index)].items[index - page_start(index)].id)
        not in excluded_user_ids
    ]


def _visible_rank_indexes(
    pages: dict[int, RankPageResult],
    *,
    excluded_user_ids: Collection[int],
) -> dict[int, int]:
    if not excluded_user_ids:
        return {
            page_start + offset: page_start + offset
            for page_start, page in pages.items()
            for offset, _item in enumerate(page.items)
        }

    visible: dict[int, int] = {}
    hidden_count = 0
    for page_start, page in sorted(pages.items()):
        for offset, item in enumerate(page.items):
            rank_index = page_start + offset
            if rank_index < EXCLUSION_PREFIX_SIZE and int(item.id) in excluded_user_ids:
                hidden_count += 1
                continue
            visible[rank_index] = rank_index - hidden_count
    return visible


def _selected_match_indexes(
    matches: list[int],
    *,
    sample_limit: int | None,
) -> set[int]:
    if sample_limit is None or len(matches) <= max(1, sample_limit):
        return set(matches)
    if sample_limit <= 1:
        return {matches[0]}
    side_count = sample_limit // 2
    return set(matches[:side_count] + matches[-side_count:])
