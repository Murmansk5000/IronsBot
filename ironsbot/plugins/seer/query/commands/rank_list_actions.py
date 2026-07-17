# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import logger

from ironsbot.integrations.headless_seer.activity import headless_operation
from ironsbot.integrations.headless_seer.client import get_game_client
from ironsbot.services.seer.local_rank_cache_queries import get_local_rank_entries
from ironsbot.services.seer.rank_list_formatting import batch_raw_start, timestamp_text
from ironsbot.services.seer.rank_list_global_messages import (
    format_global_rank_message,
)
from ironsbot.services.seer.rank_list_messages import format_local_rank_message
from ironsbot.services.seer.rank_list_score_messages import (
    format_global_rank_score_message,
)
from ironsbot.services.seer.rank_list_spec_resolution import (
    get_global_rank_spec,
    global_rank_spec_needs_sub_key,
)
from ironsbot.services.seer.rank_lookup_runtime import get_current_peak_sub_key
from ironsbot.services.seer.rank_pages import (
    fetch_daily_rank_page,
    fetch_daily_rank_page_result,
)
from ironsbot.services.seer.rank_player_query import fetch_rank_player_message
from ironsbot.services.seer.rank_score_runtime import fetch_rank_score_segment

from ..config import get_local_rank_config

if TYPE_CHECKING:
    from ironsbot.services.seer.rank_list_models import (
        GlobalRankSpec,
        LocalRankSpec,
        RankCacheBatchCommand,
        RankListCommand,
        RankPlayerCommand,
        RankScoreCommand,
    )


async def build_global_rank_message(
    spec: GlobalRankSpec,
    command: RankListCommand,
) -> str:
    spec = get_global_rank_spec(command.rank_key)
    if global_rank_spec_needs_sub_key(spec):
        return "❌找不到当前巅峰赛季数据。"
    game = get_game_client()
    with headless_operation(
        "榜单查询",
        (
            f"{spec.title} 第 "
            f"{command.start_rank}-{command.start_rank + command.limit - 1}名"
        ),
        source="榜单查询",
    ):
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
    spec = get_global_rank_spec(command.rank_key)
    if global_rank_spec_needs_sub_key(spec):
        return "❌找不到当前巅峰赛季数据。"
    game = get_game_client()
    with headless_operation(
        "榜单分数查询",
        f"{spec.title} {command.score}{spec.unit}",
        source="榜单分数查询",
    ):
        result = await fetch_rank_score_segment(
            game,
            key=spec.key,
            sub_key=spec.sub_key,
            title=spec.title,
            score_name=spec.unit,
            target_score=command.score,
            start_index=spec.start,
            rank_offset=spec.rank_offset,
            sample_limit=display_limit,
        )
    logger.info(
        "rank score lookup completed: title={} key={} sub_key={} score={} "
        "items={} total={} boundary={} searched_limit={} truncated={}",
        spec.title,
        spec.key,
        spec.sub_key,
        command.score,
        len(result.items),
        result.total_count,
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


async def build_global_rank_player_message(command: RankPlayerCommand) -> str:
    spec = get_global_rank_spec(command.rank_key)
    game = get_game_client()
    with headless_operation(
        "榜单玩家查询",
        f"{spec.title} 米米号 {command.player_id}",
        source="榜单玩家查询",
    ):
        return await fetch_rank_player_message(
            game,
            command=command,
            local_rank_enabled=get_local_rank_config().enabled,
        )


async def cache_global_rank_batch(
    command: RankCacheBatchCommand,
) -> tuple[GlobalRankSpec, int, int]:
    spec = get_global_rank_spec(command.rank_key)
    requested_count = command.end_rank - command.start_rank + 1
    if global_rank_spec_needs_sub_key(spec):
        return spec, 0, requested_count
    count = min(requested_count, get_local_rank_config().batch_limit)
    raw_start = batch_raw_start(spec, command.start_rank)
    with headless_operation(
        "手动缓存榜单",
        f"{spec.title} 第 {command.start_rank}-{command.end_rank}名",
        source="手动缓存榜单",
    ):
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
    "build_global_rank_player_message",
    "build_global_rank_score_message",
    "build_local_rank_message",
    "cache_global_rank_batch",
]
