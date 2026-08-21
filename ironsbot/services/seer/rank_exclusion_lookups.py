# SPDX-License-Identifier: GPL-3.0-or-later
"""Public-rank views layered over raw official leaderboard pages."""

from __future__ import annotations

import time
from typing import Any

from ironsbot.services.seer.rank_models import (
    RankLookupResult,
    RankPageResult,
    RankScoreGap,
    RankScoreSearchItem,
    RankScoreSearchResult,
)


async def fetch_visible_rank_range(  # noqa: PLR0913
    service: Any,
    game: Any,
    *,
    rank_key: str,
    key: int,
    sub_key: int,
    start_rank: int,
    count: int,
) -> RankPageResult:
    """Read raw pages until the requested public-rank window is complete."""

    safe_start = max(1, start_rank)
    safe_count = max(0, count)
    if safe_count == 0:
        return RankPageResult(items=[], fetched_at=time.time())
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
    fetched_at = time.time()
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
        fetched_at = max(fetched_at, page.fetched_at)
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
    return RankPageResult(
        visible_items[safe_start - 1 : visible_until],
        fetched_at,
    )


async def finalize_visible_lookup(  # noqa: PLR0913
    service: Any,
    game: Any,
    *,
    rank_key: str | None,
    key: int,
    sub_key: int,
    result: RankLookupResult,
) -> RankLookupResult:
    if result.rank is None:
        return result
    result.rank = await visible_rank_for_raw_rank(
        service,
        game,
        rank_key=rank_key,
        key=key,
        sub_key=sub_key,
        raw_rank=result.rank,
    )
    return result


async def visible_rank_for_raw_rank(  # noqa: PLR0913
    service: Any,
    game: Any,
    *,
    rank_key: str | None,
    key: int,
    sub_key: int,
    raw_rank: int,
) -> int:
    excluded_ids = service.exclusion_policy.excluded_user_ids(rank_key)
    if not excluded_ids or raw_rank <= 0:
        return raw_rank

    raw_target_index = raw_rank - 1
    remaining_ids = set(excluded_ids)
    visible_count = 0
    page_size = service.page_size()
    raw_start = 0
    while raw_start <= raw_target_index:
        page_items = await service.fetch_page(
            game,
            key=key,
            sub_key=sub_key,
            start=raw_start,
            end=raw_start + page_size - 1,
            use_cache=False,
        )
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
                return visible_count
        if len(page_items) < page_size:
            break
        if not remaining_ids:
            return raw_rank - (raw_start + page_size - visible_count)
        raw_start += page_size
    return visible_count


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
    use_superuser_limit: bool,
) -> RankScoreSearchResult:
    """Search a score segment while numbering only visible accounts."""

    limit = service._score_search_limit(
        rank_key,
        search_limit,
        use_superuser_limit=use_superuser_limit,
    )
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
    fetched_at = time.time()
    last_raw_score: int | None = None
    higher_items: list[RankScoreSearchItem] = []
    lower_items: list[RankScoreSearchItem] = []
    matches: list[RankScoreSearchItem] = []
    higher_score: int | None = None
    lower_score: int | None = None
    match_pages = 0

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
        fetched_at = max(fetched_at, page.fetched_at)
        page_has_match = False
        stop_after_page = False
        for item in page.items:
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
            if match_pages > tie_page_limit:
                result.truncated = True
                break
        if stop_after_page or len(page.items) < page_size:
            break
        raw_start += page_size

    result.fetched_at = fetched_at
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
