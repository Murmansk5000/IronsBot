# SPDX-License-Identifier: GPL-3.0-or-later
"""Public-rank views layered over raw official leaderboard pages."""

from __future__ import annotations

from typing import Any

from ironsbot.core.time import ObservationTime
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS
from ironsbot.services.seer.rank_models import (
    RankLookupResult,
    RankRangeResult,
    RankScoreGap,
    RankScoreSearchItem,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_pagination import (
    RankPageConflictError,
    RankPageSequence,
)


def _rank_page_sequence(rank_key: str | None) -> RankPageSequence:
    spec = GLOBAL_RANKS.get(rank_key) if rank_key is not None else None
    return RankPageSequence(ascending=spec.ascending if spec is not None else False)


async def fetch_visible_rank_range(  # noqa: PLR0913
    service: Any,
    game: Any,
    *,
    rank_key: str,
    key: int,
    sub_key: int,
    start_rank: int,
    count: int,
) -> RankRangeResult:
    """Read raw pages until the requested public-rank window is complete."""

    safe_start = max(1, start_rank)
    safe_count = max(0, count)
    if safe_count == 0:
        return RankRangeResult(items=[], fetched_at=None)
    excluded_ids = service.exclusion_policy.excluded_user_ids(rank_key)
    if not excluded_ids:
        return await service.fetch_range_result(
            game,
            key=key,
            sub_key=sub_key,
            start=safe_start - 1,
            count=safe_count,
        )

    visible_until = safe_start - 1 + safe_count
    visible_items: list[Any] = []
    observation = ObservationTime()
    from_cache = True
    sequence = _rank_page_sequence(rank_key)
    page_size = service.page_size()
    raw_start = 0
    while len(visible_items) < visible_until:
        page = await service.fetch_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=raw_start,
            end=raw_start + page_size - 1,
            use_cache=False,
        )
        sequence.include((int(item.id), int(item.score)) for item in page.items)
        observation.include(page.fetched_at)
        from_cache = from_cache and page.from_cache
        visible_items.extend(
            item
            for item in page.items
            if not service.exclusion_policy.excludes_from_public_rank(
                rank_key,
                int(item.id),
            )
        )
        if len(page.items) < page_size:
            break
        raw_start += page_size
    return RankRangeResult(
        visible_items[safe_start - 1 : visible_until],
        observation.fetched_at,
        from_cache=from_cache,
    )


async def finalize_visible_lookup(  # noqa: PLR0913
    service: Any,
    game: Any,
    *,
    rank_key: str | None,
    key: int,
    sub_key: int,
    result: RankLookupResult,
    user_id: int,
) -> RankLookupResult:
    if result.rank is None:
        return result
    try:
        result.rank = await visible_rank_for_raw_rank(
            service,
            game,
            rank_key=rank_key,
            key=key,
            sub_key=sub_key,
            raw_rank=result.rank,
            result=result,
            user_id=user_id,
        )
    except RankPageConflictError as error:
        result.rank = None
        result.failure = str(error)
    return result


async def visible_rank_for_raw_rank(  # noqa: PLR0913
    service: Any,
    game: Any,
    *,
    rank_key: str | None,
    key: int,
    sub_key: int,
    raw_rank: int,
    result: RankLookupResult,
    user_id: int,
) -> int:
    excluded_ids = service.exclusion_policy.excluded_user_ids(rank_key)
    if not excluded_ids or raw_rank <= 0:
        return raw_rank

    raw_target_index = raw_rank - 1
    sequence = _rank_page_sequence(rank_key)
    remaining_ids = set(excluded_ids)
    visible_count = 0
    page_size = service.page_size()
    raw_start = 0
    while raw_start <= raw_target_index:
        page = await service.fetch_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=raw_start,
            end=raw_start + page_size - 1,
            use_cache=False,
        )
        result.include_observation(page.fetched_at)
        page_items = page.items
        sequence.include((int(item.id), int(item.score)) for item in page_items)
        for offset, item in enumerate(page_items):
            raw_index = raw_start + offset
            if raw_index > raw_target_index:
                break
            item_id = int(item.id)
            if item_id in excluded_ids:
                remaining_ids.discard(item_id)
            else:
                visible_count += 1
            if raw_index == raw_target_index:
                if item_id != user_id or int(item.score) != result.score:
                    raise RankPageConflictError
                return visible_count
        if len(page_items) < page_size:
            break
        if not remaining_ids:
            return raw_rank - (raw_start + page_size - visible_count)
        raw_start += page_size
    raise RankPageConflictError


async def fetch_visible_score_segment(  # noqa: C901, PLR0912, PLR0913, PLR0915
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
) -> RankScoreSearchResult:
    """Search a score segment while numbering only visible accounts."""

    limit = service._score_search_limit(rank_key, search_limit)
    result = RankScoreSearchResult(
        title=title,
        score_name=score_name,
        target_score=target_score,
        searched_limit=limit,
        queried=limit > 0,
    )
    if target_score <= 0 or limit <= 0:
        return result

    page_size = service.page_size()
    tie_page_limit = service._tie_page_limit()
    excluded_ids = service.exclusion_policy.excluded_user_ids(rank_key)
    visible_rank = 0
    raw_start = 0
    observation = ObservationTime()
    last_raw_score: int | None = None
    higher_items: list[RankScoreSearchItem] = []
    lower_items: list[RankScoreSearchItem] = []
    matches: list[RankScoreSearchItem] = []
    higher_score: int | None = None
    lower_score: int | None = None
    match_pages = 0
    sequence = RankPageSequence()

    def make_gap(items: list[RankScoreSearchItem]) -> RankScoreGap | None:
        if not items:
            return None
        return RankScoreGap(
            score=items[0].score,
            start_rank=items[0].rank_index + 1,
            end_rank=items[-1].rank_index + 1,
            total_count=len(items),
            items=items,
        )

    while visible_rank < limit:
        page = await service.fetch_page_result(
            game,
            key=key,
            sub_key=sub_key,
            start=raw_start,
            end=raw_start + page_size - 1,
            use_cache=False,
        )
        observation.include(page.fetched_at)
        page_has_match = False
        stop_after_page = False
        sequence.include((int(item.id), int(item.score)) for item in page.items)
        for item in page.items:
            if visible_rank >= limit:
                stop_after_page = True
                break
            score = int(item.score)
            last_raw_score = score
            if int(item.id) in excluded_ids:
                continue
            visible_rank += 1
            public_item = RankScoreSearchItem(
                id=int(item.id),
                nick=str(item.nick),
                score=score,
                rank_index=visible_rank - 1,
            )
            if score > target_score:
                if higher_score != score:
                    higher_score = score
                    higher_items = []
                higher_items.append(public_item)
                continue
            if score == target_score:
                matches.append(public_item)
                page_has_match = True
                continue

            if lower_score is None:
                lower_score = score
            if score == lower_score:
                lower_items.append(public_item)
                continue
            stop_after_page = True
            break

        if page_has_match:
            match_pages += 1
        if match_pages >= tie_page_limit or visible_rank >= limit:
            result.truncated = bool(
                matches
                and lower_score is None
                and (len(page.items) == page_size or stop_after_page)
            )
            break
        if stop_after_page or len(page.items) < page_size:
            break
        raw_start += page_size

    result.fetched_at = observation.fetched_at
    result.scanned_count = len(matches)
    if matches:
        result.items = matches
        result.start_rank = matches[0].rank_index + 1
        result.end_rank = matches[-1].rank_index + 1
        result.total_count = len(matches)
        return result

    result.boundary_score = last_raw_score
    result.higher_gap = make_gap(higher_items)
    result.lower_gap = make_gap(lower_items)
    return result
