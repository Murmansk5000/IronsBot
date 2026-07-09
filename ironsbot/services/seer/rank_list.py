# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ironsbot.services.seer.rank_list_formatting import (
    batch_raw_start,
    format_rank_intervals,
    merge_rank_intervals,
    page_cache_rank_interval,
)
from ironsbot.services.seer.rank_list_formatting import (
    timestamp_text as _timestamp_text,
)
from ironsbot.services.seer.rank_list_global_messages import (
    format_global_rank_line,
    format_global_rank_message,
)
from ironsbot.services.seer.rank_list_messages import (
    build_local_rank_cache_status_message,
    build_local_rank_refresh_empty_message,
    build_local_rank_refresh_result_message,
    build_local_rank_refresh_start_message,
    build_rank_batch_no_players_message,
    build_rank_batch_result_message,
    build_rank_batch_start_message,
    build_rank_page_cache_overview_message,
    build_rank_page_cache_status_message,
    build_rank_page_refresh_result_message,
    build_rank_page_refresh_start_message,
    format_local_rank_message,
    format_refresh_ranges,
)
from ironsbot.services.seer.rank_list_models import (
    BATCH_CACHE_PREFIXES,
    GLOBAL_RANKS,
    LOCAL_RANKS,
    RANK_LIST_MAX_SIZE,
    RANK_LIST_SIZE,
    RANK_PAGE_CACHE_REFRESH_PREFIXES,
    RANK_PAGE_CACHE_STATUS_PREFIXES,
    GlobalRankSpec,
    LocalRankSpec,
    RankCacheBatchCommand,
    RankListCommand,
    RankPageCacheRefreshCommand,
    RankPageCacheStatusCommand,
    RankScoreCommand,
)
from ironsbot.services.seer.rank_list_parsing import (
    parse_rank_cache_batch_command,
    parse_rank_list_command,
    parse_rank_page_cache_refresh_command,
    parse_rank_page_cache_status_command,
    parse_rank_score_command,
    with_admin_prefix,
)
from ironsbot.services.seer.rank_list_score_messages import (
    format_global_rank_score_message,
)

__all__ = [
    "BATCH_CACHE_PREFIXES",
    "GLOBAL_RANKS",
    "LOCAL_RANKS",
    "RANK_LIST_MAX_SIZE",
    "RANK_LIST_SIZE",
    "RANK_PAGE_CACHE_REFRESH_PREFIXES",
    "RANK_PAGE_CACHE_STATUS_PREFIXES",
    "GlobalRankSpec",
    "LocalRankSpec",
    "RankCacheBatchCommand",
    "RankListCommand",
    "RankPageCacheRefreshCommand",
    "RankPageCacheStatusCommand",
    "RankScoreCommand",
    "batch_raw_start",
    "build_local_rank_cache_status_message",
    "build_local_rank_refresh_empty_message",
    "build_local_rank_refresh_result_message",
    "build_local_rank_refresh_start_message",
    "build_rank_batch_no_players_message",
    "build_rank_batch_result_message",
    "build_rank_batch_start_message",
    "build_rank_page_cache_overview_message",
    "build_rank_page_cache_status_message",
    "build_rank_page_refresh_result_message",
    "build_rank_page_refresh_start_message",
    "format_global_rank_line",
    "format_global_rank_message",
    "format_global_rank_score_message",
    "format_local_rank_message",
    "format_rank_intervals",
    "format_refresh_ranges",
    "merge_rank_intervals",
    "page_cache_rank_interval",
    "parse_rank_cache_batch_command",
    "parse_rank_list_command",
    "parse_rank_page_cache_refresh_command",
    "parse_rank_page_cache_status_command",
    "parse_rank_score_command",
    "timestamp_text",
    "with_admin_prefix",
]

def timestamp_text(timestamp: float) -> str:
    return _timestamp_text(timestamp)
