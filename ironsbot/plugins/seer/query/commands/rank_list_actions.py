# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from nonebot import logger

from ironsbot.services.seer.client import get_game_client
from ironsbot.services.seer.local_rank import get_local_rank_entries
from ironsbot.services.seer.rank_list_formatting import batch_raw_start, timestamp_text
from ironsbot.services.seer.rank_list_global_messages import (
    format_global_rank_message,
)
from ironsbot.services.seer.rank_list_messages import format_local_rank_message
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    GlobalRankSpec,
    LocalRankSpec,
    RankCacheBatchCommand,
    RankListCommand,
    RankScoreCommand,
)
from ironsbot.services.seer.rank_list_score_messages import (
    format_global_rank_score_message,
)
from ironsbot.services.seer.rank_pages import (
    fetch_daily_rank_page,
    fetch_daily_rank_page_result,
)
from ironsbot.services.seer.rank_service import (
    fetch_rank_score_segment,
    get_current_peak_sub_key,
)

from ..config import get_local_rank_config


async def build_global_rank_message(
    spec: GlobalRankSpec,
    command: RankListCommand,
) -> str:
    game = get_game_client()
    result = await fetch_daily_rank_page_result(
        game,
        key=spec.key,
        sub_key=spec.sub_key,
        start=batch_raw_start(spec, command.start_rank),
        count=command.limit,
    )
    return format_global_rank_message(
        spec,
        result.items,
        timestamp=timestamp_text(result.fetched_at),
        start_rank=command.start_rank,
        requested_count=command.limit,
    )


async def build_global_rank_score_message(
    spec: GlobalRankSpec,
    command: RankScoreCommand,
    *,
    display_limit: int,
) -> str:
    game = get_game_client()
    result = await fetch_rank_score_segment(
        game,
        key=spec.key,
        sub_key=spec.sub_key,
        title=spec.title,
        score_name=spec.unit,
        target_score=command.score,
        start_index=spec.start,
        rank_offset=spec.rank_offset,
    )
    logger.info(
        "rank score lookup completed: title={} key={} sub_key={} score={} "
        "items={} boundary={} searched_limit={} truncated={}",
        spec.title,
        spec.key,
        spec.sub_key,
        command.score,
        len(result.items),
        result.boundary_score,
        result.searched_limit,
        result.truncated,
    )
    return format_global_rank_score_message(
        spec,
        result,
        timestamp=timestamp_text(result.fetched_at) if result.fetched_at else None,
        display_limit=display_limit,
    )


async def cache_global_rank_batch(
    command: RankCacheBatchCommand,
) -> tuple[GlobalRankSpec, int, int]:
    spec = GLOBAL_RANKS[command.rank_key]
    requested_count = command.end_rank - command.start_rank + 1
    count = min(requested_count, get_local_rank_config().batch_limit)
    raw_start = batch_raw_start(spec, command.start_rank)
    items = await fetch_daily_rank_page(
        get_game_client(),
        key=spec.key,
        sub_key=spec.sub_key,
        start=raw_start,
        count=count,
        use_cache=False,
    )
    return spec, len(items), requested_count


def build_local_rank_message(spec: LocalRankSpec, command: RankListCommand) -> str:
    season_sub_key = get_current_peak_sub_key() if spec.season_limited else None
    season_sub_key_text = str(season_sub_key) if season_sub_key is not None else None
    entries, sample_count = get_local_rank_entries(
        spec.metric_key,
        limit=command.limit,
        start_rank=command.start_rank,
        season_sub_key=season_sub_key,
    )
    return format_local_rank_message(
        spec,
        entries,
        sample_count=sample_count,
        season_sub_key=season_sub_key_text,
        start_rank=command.start_rank,
        requested_count=command.limit,
    )


__all__ = [
    "build_global_rank_message",
    "build_global_rank_score_message",
    "build_local_rank_message",
    "cache_global_rank_batch",
]
