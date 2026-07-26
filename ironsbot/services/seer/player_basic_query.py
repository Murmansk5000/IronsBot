# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.player_compact_formatting import (
    format_compact_player_info,
)
from ironsbot.services.seer.player_query import (
    optional_player_extra,
    plan_player_query_sections,
)
from ironsbot.services.seer.player_service_models import PendingPlayerQuery
from ironsbot.services.seer.rank_models import PeakSeasonRankSummary
from ironsbot.services.seer.sequ_extra import UnityPeakInfo

if TYPE_CHECKING:
    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.services.operations.headless import HeadlessGame

logger = logging.getLogger(__name__)


async def fetch_pending_player_query(
    config: SeerConfig,
    player_id: int,
    game: HeadlessGame,
    *,
    group_id: int | None,
) -> PendingPlayerQuery:
    extra_errors: list[str] = []
    plan = plan_player_query_sections(
        config.player.sections,
        local_rank_enabled=config.local_rank.enabled,
    )

    async def fetch_basic_fields() -> tuple[Any, Any, Any]:
        with game.operations.track(
            "基础资料",
            f"米米号 {player_id}",
            source="米米号查询",
            group_id=group_id,
        ):
            user_info = await game.get_user_info(player_id)
        with game.operations.track(
            "补充资料",
            f"米米号 {player_id}",
            source="米米号查询",
            group_id=group_id,
        ):
            more_info = await game.get_more_user_info(player_id)
        if plan.needs_online_info:
            with game.operations.track(
                "在线状态",
                f"米米号 {player_id}",
                source="米米号查询",
                group_id=group_id,
            ):
                online_info = await optional_player_extra(
                    label="在线状态",
                    enabled=True,
                    awaitable_factory=lambda: game.get_user_online_info(player_id),
                    default=None,
                    extra_errors=extra_errors,
                    on_error=_log_player_extra_error,
                )
        else:
            online_info = None
        return user_info, more_info, online_info

    user_info, more_info, online_info = await asyncio.wait_for(
        fetch_basic_fields(),
        timeout=config.player.timeout_seconds,
    )
    team_name = "无"
    if getattr(user_info, "team_id", 0) > 0:
        try:
            with game.operations.track(
                "战队资料",
                f"战队 {user_info.team_id}",
                source="米米号查询",
                group_id=group_id,
            ):
                team_info = await asyncio.wait_for(
                    game.get_team_info(user_info.team_id),
                    timeout=min(5.0, config.team.timeout_seconds),
                )
            team_name = team_info.name
        except Exception:  # noqa: BLE001
            team_name = str(user_info.team_id)
    player_message = format_compact_player_info(
        user_info,
        more_info,
        team_name=team_name,
        online_info=online_info,
        unity_peak=UnityPeakInfo(),
        peak_rank_summary=PeakSeasonRankSummary.empty(),
        local_summary=LocalRankSummary(),
        show_peak=False,
        extra_errors=extra_errors,
    )
    return PendingPlayerQuery(
        player_id=player_id,
        user_info=user_info,
        more_info=more_info,
        player_message=player_message,
        section_plan=plan,
    )


def _log_player_extra_error(label: str, _error: Exception) -> None:
    logger.exception("米米号基础字段获取失败：%s", label)
