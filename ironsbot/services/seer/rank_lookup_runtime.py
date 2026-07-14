# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.config.loader import get_app_config
from ironsbot.services.seer import rank_pages
from ironsbot.services.seer.rank_constants import is_pet_kind_rank_anomaly_user
from ironsbot.services.seer.rank_lookup_service import (
    RankLookupDependencies,
)
from ironsbot.services.seer.rank_lookup_service import (
    find_pet_kind_rank as find_pet_kind_rank_with_deps,
)
from ironsbot.services.seer.rank_lookup_service import (
    find_rank as find_rank_with_deps,
)
from ironsbot.services.seer.rank_page_cache_queries import get_cached_rank_item
from ironsbot.services.seer.rank_pagination import rank_window_page_starts
from ironsbot.services.seer.rank_peak import (
    get_current_peak_sub_key as configured_peak_sub_key,
)
from ironsbot.services.seer.rank_position_cache import find_rank_by_cached_position
from ironsbot.services.seer.rank_score_lookup import (
    find_rank_by_linear_scan,
    find_rank_by_score,
)
from ironsbot.services.seer.rank_score_search import (
    score_search_probe_limit,
    score_search_tie_page_limit,
)

if TYPE_CHECKING:
    from ironsbot.config.models.seer import RankQueryConfig
    from ironsbot.services.seer.rank_models import RankLookupResult

CACHED_RANK_LOOKUP_WINDOW_PAGES = 2


def get_rank_query_config() -> RankQueryConfig:
    return get_app_config().seer.rank


def get_current_peak_sub_key() -> int | None:
    return configured_peak_sub_key(get_rank_query_config().peak_subkey)


def _rank_window_page_starts(*, center_index: int, page_size: int) -> list[int]:
    return rank_window_page_starts(
        center_index=center_index,
        page_size=page_size,
        window_pages=CACHED_RANK_LOOKUP_WINDOW_PAGES,
    )


async def _find_rank_by_cached_position(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    page_size: int,
    result: RankLookupResult,
) -> RankLookupResult | None:
    return await find_rank_by_cached_position(
        game,
        user_id=user_id,
        key=key,
        sub_key=sub_key,
        page_size=page_size,
        result=result,
        get_cached_rank_item=get_cached_rank_item,
        rank_window_page_starts=_rank_window_page_starts,
        fetch_rank_page=rank_pages.fetch_rank_page,
    )


async def _find_rank_by_linear_scan(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    limit: int,
    page_size: int,
    result: RankLookupResult,
) -> RankLookupResult:
    return await find_rank_by_linear_scan(
        game,
        user_id=user_id,
        key=key,
        sub_key=sub_key,
        limit=limit,
        page_size=page_size,
        result=result,
        fetch_rank_page=rank_pages.fetch_rank_page,
    )


def _score_search_probe_limit(limit: int) -> int:
    return score_search_probe_limit(get_rank_query_config(), limit)


def _score_search_tie_page_limit() -> int:
    return score_search_tie_page_limit(get_rank_query_config())


async def _find_rank_by_score(  # noqa: PLR0913
    game: Any,
    *,
    user_id: int,
    key: int,
    sub_key: int,
    target_score: int,
    limit: int,
    page_size: int,
    result: RankLookupResult,
) -> RankLookupResult:
    return await find_rank_by_score(
        game,
        user_id=user_id,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        limit=limit,
        page_size=page_size,
        result=result,
        score_search_probe_limit=_score_search_probe_limit,
        score_search_tie_page_limit=_score_search_tie_page_limit,
        fetch_rank_item=rank_pages.fetch_rank_item,
        fetch_rank_page=rank_pages.fetch_rank_page,
    )


def _online_search_limit(search_limit: int | None = None) -> int:
    rank_config = get_rank_query_config()
    configured_limit = max(0, rank_config.limit)
    requested_limit = configured_limit if search_limit is None else max(0, search_limit)
    return min(requested_limit, max(0, rank_config.online_limit))


def _score_search_limit(search_limit: int | None = None) -> int:
    rank_config = get_rank_query_config()
    configured_limit = max(0, rank_config.limit)
    requested_limit = configured_limit if search_limit is None else max(0, search_limit)
    return min(requested_limit, configured_limit)


def rank_lookup_dependencies() -> RankLookupDependencies:
    return RankLookupDependencies(
        online_search_limit=_online_search_limit,
        score_search_limit=_score_search_limit,
        page_size=lambda: max(1, min(get_rank_query_config().page_size, 100)),
        is_pet_kind_rank_anomaly_user=is_pet_kind_rank_anomaly_user,
        find_rank_by_cached_position=_find_rank_by_cached_position,
        find_rank_by_score=_find_rank_by_score,
        find_rank_by_linear_scan=_find_rank_by_linear_scan,
    )


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
) -> RankLookupResult:
    return await find_rank_with_deps(
        game,
        user_id=user_id,
        title=title,
        score_name=score_name,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        search_limit=search_limit,
        deps=rank_lookup_dependencies(),
    )


async def find_pet_kind_rank(
    game: Any,
    *,
    user_id: int,
    pet_kind_count: int,
    search_limit: int,
) -> RankLookupResult:
    return await find_pet_kind_rank_with_deps(
        game,
        user_id=user_id,
        pet_kind_count=pet_kind_count,
        search_limit=search_limit,
        deps=rank_lookup_dependencies(),
    )
