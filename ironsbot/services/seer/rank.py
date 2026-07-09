# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any

from ironsbot.config import get_app_config
from ironsbot.config.models.seer import LocalRankConfig, RankQueryConfig
from ironsbot.services.seer.rank_constants import (
    PET_KIND_RANK_ANOMALY_USER_IDS,
)
from ironsbot.services.seer.rank_fetching import fetch_rank_page_result_from_game
from ironsbot.services.seer.rank_formatting import (
    format_book_breakdown as _format_book_breakdown,
)
from ironsbot.services.seer.rank_formatting import (
    format_peak_rank_lookup as _format_peak_rank_lookup,
)
from ironsbot.services.seer.rank_formatting import (
    format_player_rank_summary as _format_player_rank_summary,
)
from ironsbot.services.seer.rank_formatting import (
    format_rank_lookup as _format_rank_lookup,
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
from ironsbot.services.seer.rank_models import (
    BookBreakdownSummary,
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
    RankPageResult,
    RankScoreMissProof,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_page_cache import (
    get_cached_rank_item,
    get_cached_rank_item_by_index,
    get_cached_rank_page_result,
    get_cached_rank_score_indexes,
    get_rank_page_cache_summary,
    save_rank_page,
)
from ironsbot.services.seer.rank_pagination import (
    rank_page_size,
    rank_page_start,
    rank_window_page_starts,
)
from ironsbot.services.seer.rank_peak import (
    build_peak_rating_score as _build_peak_rating_score_impl,
)
from ironsbot.services.seer.rank_peak import (
    datetime_to_sub_key as _datetime_to_sub_key_impl,
)
from ironsbot.services.seer.rank_peak import (
    get_current_peak_sub_key as _get_current_peak_sub_key_impl,
)
from ironsbot.services.seer.rank_position_cache import (
    find_rank_by_cached_position as _find_rank_by_cached_position_impl,
)
from ironsbot.services.seer.rank_range import (
    fetch_rank_range as _fetch_rank_range_impl,
)
from ironsbot.services.seer.rank_range import (
    fetch_rank_range_result as _fetch_rank_range_result_impl,
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
    RankScoreSegmentDependencies,
    score_search_probe_limit,
    score_search_tie_page_limit,
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
from ironsbot.services.seer.rank_summary import (
    fetch_autocard_rank_summary as _fetch_autocard_rank_summary_impl,
)
from ironsbot.services.seer.rank_summary import (
    fetch_book_breakdown_summary as _fetch_book_breakdown_summary_impl,
)
from ironsbot.services.seer.rank_summary import (
    fetch_peak_season_rank_summary as _fetch_peak_season_rank_summary_impl,
)
from ironsbot.services.seer.rank_summary import (
    fetch_player_rank_summary as _fetch_player_rank_summary_impl,
)

format_book_breakdown = _format_book_breakdown
format_peak_rank_lookup = _format_peak_rank_lookup
format_player_rank_summary = _format_player_rank_summary
format_rank_lookup = _format_rank_lookup

BOOK_BREAKDOWN_SCAN_LIMIT = 2_000
CACHED_RANK_LOOKUP_WINDOW_PAGES = 2


def get_rank_query_config() -> RankQueryConfig:
    return get_app_config().seer.rank


def get_local_rank_config() -> LocalRankConfig:
    return get_app_config().seer.local_rank


def _rank_page_size() -> int:
    return rank_page_size(get_rank_query_config())


def _rank_page_start(index: int) -> int:
    return rank_page_start(index, page_size=_rank_page_size())


def is_pet_kind_rank_anomaly_user(user_id: int) -> bool:
    return user_id in PET_KIND_RANK_ANOMALY_USER_IDS


async def _fetch_rank_page_result(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    use_cache: bool = False,
) -> RankPageResult:
    return await fetch_rank_page_result_from_game(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        end=end,
        use_cache=use_cache,
        get_cached_page=get_cached_rank_page_result,
        save_page=save_rank_page,
    )


async def _fetch_rank_page(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    use_cache: bool = False,
) -> list[Any]:
    result = await _fetch_rank_page_result(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        end=end,
        use_cache=use_cache,
    )
    return result.items


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
        fetch_rank_page=_fetch_rank_page,
    )


async def _fetch_rank_item(
    game: Any,
    *,
    key: int,
    sub_key: int,
    index: int,
    use_cache: bool = False,
) -> Any | None:
    if use_cache:
        cached_item = get_cached_rank_item_by_index(
            key=key,
            sub_key=sub_key,
            rank_index=index,
        )
        if cached_item is not None:
            return cached_item

    page_size = _rank_page_size()
    page_start = _rank_page_start(index)
    items = await _fetch_rank_page(
        game,
        key=key,
        sub_key=sub_key,
        start=page_start,
        end=page_start + page_size - 1,
        use_cache=use_cache,
    )
    offset = index - page_start
    return items[offset] if 0 <= offset < len(items) else None


async def fetch_daily_rank_page(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    count: int,
    use_cache: bool = False,
) -> list[Any]:
    return await _fetch_rank_range_impl(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        count=count,
        use_cache=use_cache,
        rank_page_size=_rank_page_size,
        fetch_rank_page_result=_fetch_rank_page_result,
    )


async def fetch_daily_rank_page_result(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    start: int,
    count: int,
    use_cache: bool = False,
) -> RankPageResult:
    return await _fetch_rank_range_result_impl(
        game,
        key=key,
        sub_key=sub_key,
        start=start,
        count=count,
        use_cache=use_cache,
        rank_page_size=_rank_page_size,
        fetch_rank_page_result=_fetch_rank_page_result,
    )


def _datetime_to_sub_key(value: Any) -> int:
    return _datetime_to_sub_key_impl(value)


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
        fetch_rank_page=_fetch_rank_page,
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
        fetch_rank_item=_fetch_rank_item,
        fetch_rank_page=_fetch_rank_page,
    )


def _cached_score_candidate_page_starts(
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
) -> list[int]:
    return _cached_score_candidate_page_starts_impl(
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_page_start=_rank_page_start,
        get_cached_score_indexes=get_cached_rank_score_indexes,
        get_cache_summary=get_rank_page_cache_summary,
    )


def _cached_score_miss_boundary(  # noqa: PLR0913
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
    rank_offset: int,
) -> RankScoreMissProof | None:
    return _cached_score_miss_boundary_impl(
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
        get_cache_summary=get_rank_page_cache_summary,
        get_cached_score_indexes=get_cached_rank_score_indexes,
        get_cached_page_result=get_cached_rank_page_result,
        score_miss_proof_from_page=_score_miss_proof_from_page,
    )


async def _fetch_rank_score_segment_from_cached_candidates(  # noqa: PLR0913
    game: Any,
    *,
    key: int,
    sub_key: int,
    target_score: int,
    start_index: int,
    end_index: int,
    rank_offset: int,
    result: RankScoreSearchResult,
    candidate_starts: list[int],
) -> RankScoreSearchResult | None:
    return await _fetch_cached_score_segment_impl(
        game,
        key=key,
        sub_key=sub_key,
        target_score=target_score,
        start_index=start_index,
        end_index=end_index,
        rank_offset=rank_offset,
        result=result,
        candidate_starts=candidate_starts,
        rank_page_size=_rank_page_size,
        rank_page_start=_rank_page_start,
        score_search_tie_page_limit=_score_search_tie_page_limit,
        fetch_rank_page_result=_fetch_rank_page_result,
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
    deps = RankScoreSegmentDependencies(
        score_search_limit=_score_search_limit,
        rank_page_size=_rank_page_size,
        rank_page_start=_rank_page_start,
        cached_score_miss_boundary=_cached_score_miss_boundary,
        cached_score_candidate_page_starts=_cached_score_candidate_page_starts,
        fetch_cached_candidates=_fetch_rank_score_segment_from_cached_candidates,
        score_search_probe_limit=_score_search_probe_limit,
        score_search_tie_page_limit=_score_search_tie_page_limit,
        find_last_existing_score_index=_find_last_existing_score_index,
        fetch_rank_item=_fetch_rank_item,
        fetch_rank_page_result=_fetch_rank_page_result,
        score_miss_proof_from_page=_score_miss_proof_from_page,
    )
    return await _fetch_rank_score_segment_impl(
        game,
        key=key,
        sub_key=sub_key,
        title=title,
        score_name=score_name,
        target_score=target_score,
        search_limit=search_limit,
        start_index=start_index,
        rank_offset=rank_offset,
        deps=deps,
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


async def _fetch_book_breakdown_summary(
    game: Any,
    user_id: int,
    *,
    pet_kind_count: int = 0,
    skin_score: int | None = None,
) -> BookBreakdownSummary:
    limit = min(
        max(0, get_rank_query_config().limit),
        BOOK_BREAKDOWN_SCAN_LIMIT,
    )
    return await _fetch_book_breakdown_summary_impl(
        game,
        user_id,
        pet_kind_count=pet_kind_count,
        skin_score=skin_score,
        limit=limit,
        find_pet_kind_rank=_find_pet_kind_rank,
        find_rank=_find_rank,
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
