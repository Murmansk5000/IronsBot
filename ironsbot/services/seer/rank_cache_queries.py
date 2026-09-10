# SPDX-License-Identifier: GPL-3.0-or-later
"""Cache-only leaderboard queries used when foreground quota is exhausted."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

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
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from ironsbot.services.seer.rank_page_cache_models import CachedRankLookup


def fetch_cached_visible_rank_range(  # noqa: PLR0913
    cache: Any,
    *,
    key: int,
    sub_key: int,
    start_rank: int,
    count: int,
    page_size: int,
    excluded_user_ids: Collection[int],
) -> RankPageResult | None:
    """Return a complete requested public window without opening a game socket."""

    if count <= 0:
        return RankPageResult(items=[], fetched_at=0.0, from_cache=True)

    requested_start = max(1, start_rank)
    requested_end = requested_start + count - 1
    if not excluded_user_ids:
        return _fetch_cached_raw_range(
            cache,
            key=key,
            sub_key=sub_key,
            start_index=requested_start - 1,
            count=count,
            page_size=page_size,
        )

    visible_items: list[Any] = []
    fetched_at = 0.0
    raw_start = 0
    while len(visible_items) < requested_end:
        page = _cached_page(
            cache,
            key=key,
            sub_key=sub_key,
            start=raw_start,
            page_size=page_size,
        )
        if page is None:
            return None
        fetched_at = max(fetched_at, page.fetched_at)
        visible_items.extend(
            item for item in page.items if int(item.id) not in excluded_user_ids
        )
        if len(page.items) < page_size:
            break
        raw_start += page_size

    if len(visible_items) < requested_end:
        return None
    return RankPageResult(
        items=visible_items[requested_start - 1 : requested_end],
        fetched_at=fetched_at,
        from_cache=True,
    )


def fetch_cached_score_segment(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915
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

    if target_score <= 0 or search_limit <= 0:
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
        if aligned < start_index or aligned >= end_index:
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

    matches = _matching_indexes(pages, target_score=target_score)
    if not matches:
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
        first_start = page_start(matches[0])
        if matches[0] != first_start:
            break
        previous = read_page(first_start - page_size)
        if previous is None:
            return None
        if len(pages) > tie_page_limit:
            return None
        updated = _matching_indexes(pages, target_score=target_score)
        if updated[0] == matches[0]:
            break
        matches = updated

    while True:
        last_index = matches[-1]
        last_start = page_start(last_index)
        last = pages[last_start]
        page_end = last_start + len(last.items) - 1
        if last_index != page_end or len(last.items) < page_size:
            break
        following = read_page(last_start + page_size)
        if following is None or len(pages) > tie_page_limit:
            return None
        updated = _matching_indexes(pages, target_score=target_score)
        if updated[-1] == last_index:
            break
        matches = updated

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
            fetched_at=max(page.fetched_at for page in pages.values()),
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
        fetched_at=max(page.fetched_at for page in pages.values()),
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
) -> tuple[CachedRankLookup | None, RankLookupResult] | None:
    """Return a cached player fact or a cached complete miss proof."""

    query_id = uuid4().hex[:16]
    cached = cache.item(
        key=key,
        sub_key=sub_key,
        user_id=user_id,
        allow_stale=True,
    )
    if cached is not None:
        logger.info(
            "rank cached reply query=%s user_id=%s key=%s sub_key=%s "
            "status=found rank=%s score=%s cached_at=%s",
            query_id,
            user_id,
            key,
            sub_key,
            cached.rank_index + 1,
            cached.score,
            cached.fetched_at,
        )
        return cached, RankLookupResult(
            title=title,
            score_name=score_name,
            rank=int(cached.rank_index) + 1,
            score=int(cached.score),
            searched_limit=search_limit,
            queried=True,
            cost=RankLookupCost(cache_page_hits=1),
            query_id=query_id,
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
    logger.info(
        "rank cached reply query=%s user_id=%s key=%s sub_key=%s "
        "status=scanned_missing scanned_count=%s cached_at=%s",
        query_id,
        user_id,
        key,
        sub_key,
        miss.searched_limit,
        miss.fetched_at,
    )
    return None, RankLookupResult(
        title=title,
        score_name=score_name,
        searched_limit=int(miss.searched_limit),
        scanned_count=int(miss.searched_limit),
        scan_complete=True,
        query_id=query_id,
        queried=True,
        cost=RankLookupCost(cache_page_hits=1),
    )


def _fetch_cached_raw_range(  # noqa: PLR0913
    cache: Any,
    *,
    key: int,
    sub_key: int,
    start_index: int,
    count: int,
    page_size: int,
) -> RankPageResult | None:
    request_end = start_index + count - 1
    first_page_start = start_index // page_size * page_size
    last_page_start = request_end // page_size * page_size
    items: list[Any] = []
    fetched_at = 0.0
    for page_start in range(first_page_start, last_page_start + 1, page_size):
        page = _cached_page(
            cache,
            key=key,
            sub_key=sub_key,
            start=page_start,
            page_size=page_size,
        )
        if page is None:
            return None
        fetched_at = max(fetched_at, page.fetched_at)
        for offset, item in enumerate(page.items):
            rank_index = page_start + offset
            if start_index <= rank_index <= request_end:
                items.append(item)
    return RankPageResult(items=items, fetched_at=fetched_at, from_cache=True)


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
        allow_stale=True,
    )
    if cached is None:
        return None
    return RankPageResult(
        items=list(cached.items),
        fetched_at=float(cached.fetched_at),
        from_cache=True,
    )


def _matching_indexes(
    pages: dict[int, RankPageResult],
    *,
    target_score: int,
) -> list[int]:
    return sorted(
        page_start + offset
        for page_start, page in pages.items()
        for offset, item in enumerate(page.items)
        if int(item.score) == target_score
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
    last_page_start = page_start(matches[-1])
    for current_start in range(0, last_page_start + 1, page_size):
        if read_page(current_start) is None:
            return None
    return [
        index
        for index in matches
        if int(pages[page_start(index)].items[index - page_start(index)].id)
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
    for page_start, page in sorted(pages.items()):
        for offset, item in enumerate(page.items):
            rank_index = page_start + offset
            if int(item.id) in excluded_user_ids:
                continue
            visible[rank_index] = len(visible)
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
