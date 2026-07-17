# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.rank_constants import (
    PET_KIND_RANK_ANOMALY_COUNT,
    PET_KIND_RANK_KEY,
    PET_KIND_RANK_SUB_KEY,
)
from ironsbot.services.seer.rank_models import RankLookupResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass(frozen=True, slots=True)
class RankLookupDependencies:
    online_search_limit: Callable[[int | None], int]
    score_search_limit: Callable[[int | None], int]
    page_size: Callable[[], int]
    is_pet_kind_rank_anomaly_user: Callable[[int], bool]
    find_rank_by_cached_position: Callable[..., Awaitable[RankLookupResult | None]]
    find_rank_by_score: Callable[..., Awaitable[RankLookupResult]]
    find_rank_by_linear_scan: Callable[..., Awaitable[RankLookupResult]]


async def find_rank(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    title: str,
    score_name: str,
    key: int,
    sub_key: int,
    target_score: int | None = None,
    search_limit: int | None = None,
    deps: RankLookupDependencies,
) -> RankLookupResult:
    score_target = (
        target_score if target_score is not None and target_score > 0 else None
    )
    limit = (
        deps.score_search_limit(search_limit)
        if score_target is not None
        else deps.online_search_limit(search_limit)
    )
    page_size = deps.page_size()

    result = RankLookupResult(
        title=title,
        score_name=score_name,
        searched_limit=limit,
        queried=limit > 0,
    )

    cached_result = await deps.find_rank_by_cached_position(
        game,
        user_id=user_id,
        key=key,
        sub_key=sub_key,
        page_size=page_size,
        result=result,
    )
    if cached_result is not None:
        return cached_result

    if limit <= 0:
        return result

    if score_target is not None:
        return await deps.find_rank_by_score(
            game,
            user_id=user_id,
            key=key,
            sub_key=sub_key,
            target_score=score_target,
            limit=limit,
            page_size=page_size,
            result=result,
        )

    return await deps.find_rank_by_linear_scan(
        game,
        user_id=user_id,
        key=key,
        sub_key=sub_key,
        limit=limit,
        page_size=page_size,
        result=result,
    )


async def find_pet_kind_rank(
    game: Any,
    *,
    user_id: int,
    pet_kind_count: int,
    search_limit: int | None,
    deps: RankLookupDependencies,
) -> RankLookupResult:
    real_search_limit = (
        deps.score_search_limit(search_limit)
        if pet_kind_count > 0
        else deps.online_search_limit(search_limit)
    )
    raw_search_limit = real_search_limit + PET_KIND_RANK_ANOMALY_COUNT
    result = RankLookupResult(
        title="精灵图鉴",
        score_name="精灵",
        score=pet_kind_count or None,
        searched_limit=real_search_limit,
        queried=real_search_limit > 0,
    )

    if deps.is_pet_kind_rank_anomaly_user(user_id):
        result.rank = 0
        if result.score is None:
            result.score = 0
        return result

    cached_result = await deps.find_rank_by_cached_position(
        game,
        user_id=user_id,
        key=PET_KIND_RANK_KEY,
        sub_key=PET_KIND_RANK_SUB_KEY,
        page_size=deps.page_size(),
        result=result,
    )
    if cached_result is not None:
        cached_result.searched_limit = real_search_limit
        if cached_result.rank is not None:
            cached_result.rank = max(
                0, cached_result.rank - PET_KIND_RANK_ANOMALY_COUNT
            )
        return cached_result

    if real_search_limit <= 0:
        return result

    if pet_kind_count > 0:
        raw_result = await deps.find_rank_by_score(
            game,
            user_id=user_id,
            key=PET_KIND_RANK_KEY,
            sub_key=PET_KIND_RANK_SUB_KEY,
            target_score=pet_kind_count,
            limit=raw_search_limit,
            page_size=deps.page_size(),
            result=result,
        )
    else:
        raw_result = await deps.find_rank_by_linear_scan(
            game,
            user_id=user_id,
            key=PET_KIND_RANK_KEY,
            sub_key=PET_KIND_RANK_SUB_KEY,
            limit=raw_search_limit,
            page_size=deps.page_size(),
            result=result,
        )
    raw_result.searched_limit = real_search_limit
    if raw_result.rank is not None:
        raw_result.rank = max(0, raw_result.rank - PET_KIND_RANK_ANOMALY_COUNT)
    return raw_result


__all__ = ["RankLookupDependencies", "find_pet_kind_rank", "find_rank"]
