# SPDX-License-Identifier: GPL-3.0-or-later
"""Public leaderboard numbering shared by lists, score searches and players."""

from __future__ import annotations

from typing import Any

from ironsbot.core.rank_lookup_context import rank_page_policy
from ironsbot.services.seer.rank_models import (
    RankLookupResult,
    RankPageResult,
    RankRangeResult,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_pagination import RankPageConflictError
from ironsbot.services.seer.rank_visibility import EXCLUSION_PREFIX_SIZE
from ironsbot.services.seer.rank_visibility_queries import RankVisibilityQuery


def _validate_prefix_player(
    prefix: list[Any], index: int, result: RankLookupResult, user_id: int
) -> None:
    if len(prefix) < min(index + 1, EXCLUSION_PREFIX_SIZE):
        raise RankPageConflictError
    if index < len(prefix):
        item = prefix[index]
        if int(item.id) != user_id or int(item.score) != result.score:
            raise RankPageConflictError


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
    query = RankVisibilityQuery(service, game, rank_key, key, sub_key)
    return await query.range(start_rank, count)


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
    query = RankVisibilityQuery(service, game, rank_key, key, sub_key)
    try:
        visibility = await query.visibility(raw_until=result.rank)
        for page in query.pages.values():
            result.include_observation(page.fetched_at)
        raw_index = result.rank - 1
        if visibility.filtered_prefix and visibility.excluded_ids:
            _validate_prefix_player(query.prefix, raw_index, result, user_id)
        if visibility.hides(raw_index, user_id):
            result.rank = None
            result.excluded = True
        else:
            result.rank = visibility.public_index(raw_index) + 1
        query.log_complete(visibility, start_rank=result.rank, count=1)
    except RankPageConflictError as error:
        result.rank = None
        result.failure = str(error)
    result.cost.conflict_retries = int(query.retried)
    return result


async def fetch_visible_score_segment(  # noqa: PLR0913
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
    start_index: int = 0,
    sample_limit: int | None = None,
) -> RankScoreSearchResult:
    query = RankVisibilityQuery(service, game, rank_key, key, sub_key)

    async def fetch_page(
        _game: Any, *, start: int, end: int, **_kwargs: Any
    ) -> RankPageResult:
        policy = rank_page_policy.get()
        if policy is not None and policy.phase == "score_tie":
            size = service.page_size()
            for page_start in range(start // size * size, end + 1, size):
                query.pages.pop(page_start, None)
        window = await query.raw_range(start, end - start + 1)
        return RankPageResult(window.items, window.fetched_at or 0.0, window.from_cache)

    async def read() -> RankScoreSearchResult:
        return await service._fetch_raw_score_segment(
            game,
            rank_key=rank_key,
            key=key,
            sub_key=sub_key,
            title=title,
            score_name=score_name,
            target_score=target_score,
            search_limit=search_limit,
            start_index=start_index,
            sample_limit=None
            if rank_key is not None
            and service.exclusion_policy.excluded_user_ids(rank_key)
            else sample_limit,
            fetch_page=fetch_page,
        )

    result = await query.recover("target", read)
    last_rank = max(
        result.end_rank or 0,
        *(
            gap.end_rank if gap is not None else 0
            for gap in (result.higher_gap, result.lower_gap)
        ),
    )
    visibility = await query.visibility(raw_until=last_rank)
    for page in query.pages.values():
        result.fetched_at = (
            min(result.fetched_at, page.fetched_at)
            if result.fetched_at is not None
            else page.fetched_at
        )
    result = visibility.apply_score_result(result)
    query.log_complete(
        visibility, start_rank=result.start_rank, count=len(result.items)
    )
    return result
