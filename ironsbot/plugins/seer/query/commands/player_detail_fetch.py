# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot import logger

from ironsbot.integrations.headless_seer.activity import headless_operation
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.player_detail_formatting import (
    format_player_detail_messages,
)
from ironsbot.services.seer.player_query import (
    PlayerDetailErrors,
    PlayerDetailMessages,
    calculate_player_peak_scores,
    optional_player_extra,
    plan_player_detail_fetches,
    validate_player_peak_season,
)
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
    RankSummaryProgress,
)
from ironsbot.services.seer.rank_summary_runtime import (
    fetch_autocard_rank_summary,
    fetch_peak_season_rank_summary,
    fetch_player_rank_summary,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakInfo,
    fetch_unity_part_one,
    fetch_unity_peak,
)

if TYPE_CHECKING:
    from typing import Any

    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.integrations.headless_seer.game import SeerGame
    from ironsbot.services.seer.local_rank import LocalRankService


def create_player_detail_task(  # noqa: PLR0913
    local_rank: LocalRankService,
    game: SeerGame,
    *,
    player_id: int,
    user_info: Any,
    more_info: Any,
    has_collection: bool,
    needs_peak_section: bool,
    has_autocard_rank: bool,
    show_local_rank: bool,
    config: SeerConfig,
) -> asyncio.Task[PlayerDetailMessages]:
    task = asyncio.create_task(
        _build_player_detail_messages(
            game=game,
            player_id=player_id,
            user_info=user_info,
            more_info=more_info,
            has_collection=has_collection,
            needs_peak_section=needs_peak_section,
            has_autocard_rank=has_autocard_rank,
            show_local_rank=show_local_rank,
            config=config,
            local_rank=local_rank,
        )
    )
    task.add_done_callback(_log_unrequested_player_detail_task_error)
    return task


def _log_player_extra_error(label: str, _error: Exception) -> None:
    logger.opt(exception=True).warning(f"米米号扩展字段获取失败：{label}")


def _log_unrequested_player_detail_task_error(
    task: asyncio.Task[PlayerDetailMessages],
) -> None:
    try:
        exception = task.exception()
    except asyncio.CancelledError:
        return

    if exception is not None:
        logger.opt(exception=exception).warning("米米号后台详情任务失败")


async def _build_player_detail_messages(  # noqa: PLR0913
    *,
    game: SeerGame,
    player_id: int,
    user_info: Any,
    more_info: Any,
    has_collection: bool,
    needs_peak_section: bool,
    has_autocard_rank: bool,
    show_local_rank: bool,
    config: SeerConfig,
    local_rank: LocalRankService,
) -> PlayerDetailMessages:
    extra_errors = PlayerDetailErrors()
    extra_timeout_seconds = min(
        float(config.player.timeout_seconds),
        float(config.player.detail_timeout_seconds),
    )
    fetch_plan = plan_player_detail_fetches(
        has_collection=has_collection,
        needs_peak_section=needs_peak_section,
        has_autocard_rank=has_autocard_rank,
        local_rank_enabled=config.local_rank.enabled,
    )

    with headless_operation(
        "米米号详情查询",
        f"米米号 {player_id}",
        source="米米号详情查询",
    ):
        unity_part_one, unity_peak = await asyncio.gather(
            optional_player_extra(
                "展示/收集数据",
                fetch_plan.needs_unity_part_one,
                lambda: fetch_unity_part_one(game, player_id),
                UnityPartOneInfo(),
                extra_errors.collection,
                on_error=_log_player_extra_error,
                timeout_seconds=extra_timeout_seconds,
            ),
            optional_player_extra(
                "巅峰数据",
                fetch_plan.needs_unity_peak,
                lambda: fetch_unity_peak(game, player_id),
                UnityPeakInfo(),
                extra_errors.peak,
                on_error=_log_player_extra_error,
                timeout_seconds=extra_timeout_seconds,
            ),
        )
        peak_sub_key = local_rank.current_peak_sub_key()
        peak_scores = calculate_player_peak_scores(unity_peak)
        rank_progress = RankSummaryProgress()
        peak_rank_progress = RankSummaryProgress()
        rank_summary, peak_rank_summary, autocard_rank_summary = await asyncio.gather(
            optional_player_extra(
                "全服排行",
                fetch_plan.needs_rank_summary,
                lambda: fetch_player_rank_summary(
                    game,
                    player_id,
                    achieve_score=getattr(more_info, "total_achieve", None),
                    pet_kind_count=unity_part_one.pet_kind_num,
                    skin_score=unity_part_one.skin_num,
                    progress=rank_progress,
                ),
                PlayerRankSummary.empty(),
                extra_errors.collection,
                on_error=_log_player_extra_error,
                timeout_seconds=extra_timeout_seconds,
                error_label_factory=lambda: rank_progress.current_title
                or "全服排行",
            ),
            optional_player_extra(
                "巅峰赛季榜",
                needs_peak_section,
                lambda: fetch_peak_season_rank_summary(
                    game,
                    player_id,
                    standard_score=peak_scores.standard,
                    wild_score=peak_scores.wild,
                    expert_score=peak_scores.expert,
                    progress=peak_rank_progress,
                ),
                PeakSeasonRankSummary.empty(),
                extra_errors.peak,
                on_error=_log_player_extra_error,
                timeout_seconds=extra_timeout_seconds,
                error_label_factory=lambda: peak_rank_progress.current_title
                or "巅峰赛季榜",
            ),
            optional_player_extra(
                "群星牌排行",
                fetch_plan.needs_autocard_rank,
                lambda: fetch_autocard_rank_summary(game, player_id),
                RankLookupResult(title="群星之巅榜", score_name="分"),
                extra_errors.autocard,
                on_error=_log_player_extra_error,
                timeout_seconds=extra_timeout_seconds,
            ),
        )
        extra_errors.collection.extend(rank_summary.errors)
        extra_errors.peak.extend(peak_rank_summary.errors)
        validated_peak = validate_player_peak_season(
            unity_peak,
            peak_scores,
            peak_rank_summary,
        )
        local_rank_summary = await optional_player_extra(
            "机器人查询排行",
            fetch_plan.needs_local_rank,
            lambda: local_rank.update_cache(
                player_id=player_id,
                nick=user_info.nick,
                more_info=more_info,
                unity_part_one=unity_part_one,
                unity_peak=validated_peak.unity_peak,
                rank_summary=rank_summary,
                autocard_rank_summary=autocard_rank_summary,
                peak_sub_key=peak_sub_key,
                peak_standard_score=validated_peak.scores.standard,
                peak_wild_score=validated_peak.scores.wild,
                peak_expert_score=validated_peak.scores.expert,
                clear_metric_keys=validated_peak.clear_metric_keys,
            ),
            LocalRankSummary(),
            extra_errors.shared,
            on_error=_log_player_extra_error,
            timeout_seconds=extra_timeout_seconds,
        )
    return format_player_detail_messages(
        player_id=player_id,
        user_info=user_info,
        more_info=more_info,
        unity_part_one=unity_part_one,
        unity_peak=unity_peak,
        rank_summary=rank_summary,
        peak_rank_summary=peak_rank_summary,
        autocard_rank_summary=autocard_rank_summary,
        local_rank_summary=local_rank_summary,
        empty_local_rank_summary=LocalRankSummary(),
        has_collection=has_collection,
        needs_peak_section=needs_peak_section,
        has_autocard_rank=has_autocard_rank,
        show_local_rank=show_local_rank,
        extra_errors=extra_errors,
    )
