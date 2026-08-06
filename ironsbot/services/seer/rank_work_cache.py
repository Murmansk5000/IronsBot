# SPDX-License-Identifier: GPL-3.0-or-later
"""Query-work and negative-result adapters for the rank page cache."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ironsbot.services.seer.query_work import (
    record_cached_query_work,
    record_successful_query_work,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.rank_exclusions import RankExclusionPolicy
    from ironsbot.services.seer.rank_page_cache_models import CachedRankMiss


def record_rank_page_work(
    policy: RankExclusionPolicy,
    *,
    key: int,
    sub_key: int,
    cached: bool,
) -> None:
    rank_key = policy.rank_key_for_protocol(key=key, sub_key=sub_key)
    if rank_key is None:
        return
    work_unit = f"rank:{rank_key}"
    if cached:
        record_cached_query_work(work_unit)
    else:
        record_successful_query_work(work_unit)


def cached_rank_miss(
    cache: object,
    *,
    key: int,
    sub_key: int,
    user_id: int,
    minimum_limit: int,
) -> CachedRankMiss | None:
    get_miss = getattr(cache, "miss", None)
    if not callable(get_miss):
        return None
    return cast(
        "CachedRankMiss | None",
        get_miss(
            key=key,
            sub_key=sub_key,
            user_id=user_id,
            minimum_limit=minimum_limit,
        ),
    )


def save_rank_miss(
    cache: object,
    *,
    key: int,
    sub_key: int,
    user_id: int,
    searched_limit: int,
) -> None:
    save_miss = getattr(cache, "save_miss", None)
    if callable(save_miss):
        save_miss(
            key=key,
            sub_key=sub_key,
            user_id=user_id,
            searched_limit=searched_limit,
        )
