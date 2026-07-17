# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.config.loader import get_app_config
from ironsbot.services.seer import rank_pages
from ironsbot.services.seer.rank_page_cache_queries import (
    get_cached_rank_page_result,
    get_cached_rank_score_indexes,
    get_rank_page_cache_summary,
)
from ironsbot.services.seer.rank_score_cache import (
    cached_score_candidate_page_starts,
    cached_score_miss_boundary,
    fetch_rank_score_segment_from_cached_candidates,
)
from ironsbot.services.seer.rank_score_helpers import score_miss_proof_from_page
from ironsbot.services.seer.rank_score_search import (
    score_search_probe_limit,
    score_search_tie_page_limit,
)
from ironsbot.services.seer.rank_score_segments import (
    fetch_rank_score_segment as fetch_rank_score_segment_online,
)
from ironsbot.services.seer.rank_score_service import (
    RankScoreServiceDependencies,
)
from ironsbot.services.seer.rank_score_service import (
    fetch_rank_score_segment as fetch_rank_score_segment_with_deps,
)

if TYPE_CHECKING:
    from ironsbot.config.models.seer import RankQueryConfig
    from ironsbot.services.seer.rank_models import RankScoreSearchResult


def get_rank_query_config() -> RankQueryConfig:
    return get_app_config().seer.rank


def _score_search_limit(search_limit: int | None = None) -> int:
    rank_config = get_rank_query_config()
    configured_limit = max(0, rank_config.limit)
    requested_limit = configured_limit if search_limit is None else max(0, search_limit)
    return min(requested_limit, configured_limit)


def _score_search_probe_limit(limit: int) -> int:
    return score_search_probe_limit(get_rank_query_config(), limit)


def _score_search_tie_page_limit() -> int:
    return score_search_tie_page_limit(get_rank_query_config())


def rank_score_service_dependencies() -> RankScoreServiceDependencies:
    return RankScoreServiceDependencies(
        rank_page_size=rank_pages.rank_page_size,
        rank_page_start=rank_pages.rank_page_start,
        score_search_limit=_score_search_limit,
        score_search_probe_limit=_score_search_probe_limit,
        score_search_tie_page_limit=_score_search_tie_page_limit,
        get_cached_score_indexes=get_cached_rank_score_indexes,
        get_cache_summary=get_rank_page_cache_summary,
        get_cached_page_result=get_cached_rank_page_result,
        score_miss_proof_from_page=score_miss_proof_from_page,
        fetch_cached_candidates_impl=fetch_rank_score_segment_from_cached_candidates,
        fetch_rank_score_segment_impl=fetch_rank_score_segment_online,
        cached_score_candidate_page_starts_impl=cached_score_candidate_page_starts,
        cached_score_miss_boundary_impl=cached_score_miss_boundary,
        fetch_rank_item=rank_pages.fetch_rank_item,
        fetch_rank_page_result=rank_pages.fetch_rank_page_result,
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
    sample_limit: int | None = None,
) -> RankScoreSearchResult:
    return await fetch_rank_score_segment_with_deps(
        game,
        key=key,
        sub_key=sub_key,
        title=title,
        score_name=score_name,
        target_score=target_score,
        search_limit=search_limit,
        start_index=start_index,
        rank_offset=rank_offset,
        sample_limit=sample_limit,
        deps=rank_score_service_dependencies(),
    )
