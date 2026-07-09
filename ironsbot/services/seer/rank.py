# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.config.loader import get_app_config
from ironsbot.services.seer import rank_pages
from ironsbot.services.seer.rank_constants import (
    PET_KIND_RANK_ANOMALY_USER_IDS,
)
from ironsbot.services.seer.rank_lookup_service import (
    RankLookupDependencies,
)
from ironsbot.services.seer.rank_lookup_service import (
    find_pet_kind_rank as _find_pet_kind_rank_impl,
)
from ironsbot.services.seer.rank_lookup_service import (
    find_rank as _find_rank_impl,
)
from ironsbot.services.seer.rank_page_cache import (
    get_cached_rank_item,
    get_cached_rank_page_result,
    get_cached_rank_score_indexes,
    get_rank_page_cache_summary,
)
from ironsbot.services.seer.rank_pagination import (
    rank_window_page_starts,
)
from ironsbot.services.seer.rank_peak import (
    build_peak_rating_score as _build_peak_rating_score_impl,
)
from ironsbot.services.seer.rank_peak import (
    get_current_peak_sub_key as _get_current_peak_sub_key_impl,
)
from ironsbot.services.seer.rank_position_cache import (
    find_rank_by_cached_position as _find_rank_by_cached_position_impl,
)
from ironsbot.services.seer.rank_score_cache import (
    cached_score_candidate_page_starts as _cached_score_candidate_page_starts_impl,
)
from ironsbot.services.seer.rank_score_cache import (
    cached_score_miss_boundary as _cached_score_miss_boundary_impl,
)
from ironsbot.services.seer.rank_score_cache import (
    fetch_rank_score_segment_from_cached_candidates as _fetch_cached_score_segment_impl,
)
from ironsbot.services.seer.rank_score_helpers import (
    score_miss_proof_from_page as _score_miss_proof_from_page,
)
from ironsbot.services.seer.rank_score_search import (
    fetch_rank_score_segment as _fetch_rank_score_segment_impl,
)
from ironsbot.services.seer.rank_score_search import (
    find_last_existing_score_index as _find_last_existing_score_index,
)
from ironsbot.services.seer.rank_score_search import (
    find_rank_by_linear_scan as _find_rank_by_linear_scan_impl,
)
from ironsbot.services.seer.rank_score_search import (
    find_rank_by_score as _find_rank_by_score_impl,
)
from ironsbot.services.seer.rank_score_search import (
    score_search_probe_limit,
    score_search_tie_page_limit,
)
from ironsbot.services.seer.rank_score_service import (
    RankScoreServiceDependencies,
)
from ironsbot.services.seer.rank_score_service import (
    fetch_rank_score_segment as _fetch_rank_score_segment_service,
)
from ironsbot.services.seer.rank_summary import (
    fetch_autocard_rank_summary as _fetch_autocard_rank_summary_impl,
)
from ironsbot.services.seer.rank_summary import (
    fetch_peak_season_rank_summary as _fetch_peak_season_rank_summary_impl,
)
from ironsbot.services.seer.rank_summary import (
    fetch_player_rank_summary as _fetch_player_rank_summary_impl,
)

if TYPE_CHECKING:
    from ironsbot.config.models.seer import LocalRankConfig, RankQueryConfig
    from ironsbot.services.seer.rank_models import (
        PeakSeasonRankSummary,
        PlayerRankSummary,
        RankLookupResult,
        RankScoreSearchResult,
    )

BOOK_BREAKDOWN_SCAN_LIMIT = 2_000
CACHED_RANK_LOOKUP_WINDOW_PAGES = 2


def get_rank_query_config() -> RankQueryConfig:
    return get_app_config().seer.rank


def get_local_rank_config() -> LocalRankConfig:
    return get_app_config().seer.local_rank


def is_pet_kind_rank_anomaly_user(user_id: int) -> bool:
    return user_id in PET_KIND_RANK_ANOMALY_USER_IDS


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
    return await _find_rank_by_cached_position_impl(
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


def get_current_peak_sub_key() -> int | None:
    return _get_current_peak_sub_key_impl(get_rank_query_config().peak_subkey)


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
    return await _find_rank_by_linear_scan_impl(
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
    return await _find_rank_by_score_impl(
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
        find_last_existing_score_index=_find_last_existing_score_index,
        fetch_rank_item=rank_pages.fetch_rank_item,
        fetch_rank_page=rank_pages.fetch_rank_page,
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
) -> RankScoreSearchResult:
    return await _fetch_rank_score_segment_service(
        game,
        key=key,
        sub_key=sub_key,
        title=title,
        score_name=score_name,
        target_score=target_score,
        search_limit=search_limit,
        start_index=start_index,
        rank_offset=rank_offset,
        deps=_rank_score_service_dependencies(),
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


def _rank_score_service_dependencies() -> RankScoreServiceDependencies:
    return RankScoreServiceDependencies(
        rank_page_size=rank_pages.rank_page_size,
        rank_page_start=rank_pages.rank_page_start,
        score_search_limit=_score_search_limit,
        score_search_probe_limit=_score_search_probe_limit,
        score_search_tie_page_limit=_score_search_tie_page_limit,
        get_cached_score_indexes=get_cached_rank_score_indexes,
        get_cache_summary=get_rank_page_cache_summary,
        get_cached_page_result=get_cached_rank_page_result,
        score_miss_proof_from_page=_score_miss_proof_from_page,
        fetch_cached_candidates_impl=_fetch_cached_score_segment_impl,
        fetch_rank_score_segment_impl=_fetch_rank_score_segment_impl,
        cached_score_candidate_page_starts_impl=(
            _cached_score_candidate_page_starts_impl
        ),
        cached_score_miss_boundary_impl=_cached_score_miss_boundary_impl,
        find_last_existing_score_index=_find_last_existing_score_index,
        fetch_rank_item=rank_pages.fetch_rank_item,
        fetch_rank_page_result=rank_pages.fetch_rank_page_result,
    )


def _rank_lookup_dependencies() -> RankLookupDependencies:
    return RankLookupDependencies(
        online_search_limit=_online_search_limit,
        score_search_limit=_score_search_limit,
        page_size=lambda: max(1, min(get_rank_query_config().page_size, 100)),
        is_pet_kind_rank_anomaly_user=is_pet_kind_rank_anomaly_user,
        find_rank_by_cached_position=_find_rank_by_cached_position,
        find_rank_by_score=_find_rank_by_score,
        find_rank_by_linear_scan=_find_rank_by_linear_scan,
    )


async def _find_rank(  # noqa: PLR0913
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
    return await _find_rank_impl(
        game,
        user_id=user_id,
        title=title,
        score_name=score_name,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        search_limit=search_limit,
        deps=_rank_lookup_dependencies(),
    )


async def _find_pet_kind_rank(
    game: Any,
    *,
    user_id: int,
    pet_kind_count: int,
    search_limit: int,
) -> RankLookupResult:
    return await _find_pet_kind_rank_impl(
        game,
        user_id=user_id,
        pet_kind_count=pet_kind_count,
        search_limit=search_limit,
        deps=_rank_lookup_dependencies(),
    )


async def fetch_peak_season_rank_summary(
    game: Any,
    user_id: int,
    *,
    standard_score: int | None = None,
    wild_score: int | None = None,
    expert_score: int | None = None,
) -> PeakSeasonRankSummary:
    return await _fetch_peak_season_rank_summary_impl(
        game,
        user_id,
        standard_score=standard_score,
        wild_score=wild_score,
        expert_score=expert_score,
        current_peak_sub_key=get_current_peak_sub_key(),
        find_rank=_find_rank,
    )


async def fetch_autocard_rank_summary(
    game: Any,
    user_id: int,
) -> RankLookupResult:
    return await _fetch_autocard_rank_summary_impl(
        game,
        user_id,
        find_rank=_find_rank,
    )


async def fetch_player_rank_summary(  # noqa: PLR0913
    game: Any,
    user_id: int,
    *,
    book_score: int | None = None,
    achieve_score: int | None = None,
    pet_kind_count: int = 0,
    skin_score: int | None = None,
) -> PlayerRankSummary:
    limit = min(
        max(0, get_rank_query_config().limit),
        BOOK_BREAKDOWN_SCAN_LIMIT,
    )
    return await _fetch_player_rank_summary_impl(
        game,
        user_id,
        book_score=book_score,
        achieve_score=achieve_score,
        pet_kind_count=pet_kind_count,
        skin_score=skin_score,
        book_breakdown_limit=limit,
        find_rank=_find_rank,
        find_pet_kind_rank=_find_pet_kind_rank,
    )


def build_peak_rating_score(rank: int, star: int) -> int | None:
    return _build_peak_rating_score_impl(rank, star)
