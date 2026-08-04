# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.player_compact_formatting import (
    format_compact_player_info,
)
from ironsbot.services.seer.player_query import (
    optional_player_extra,
    plan_player_query_sections,
)
from ironsbot.services.seer.player_service_models import (
    PendingPlayerQuery,
    PlayerBaseSnapshot,
)
from ironsbot.services.seer.rank_models import PeakSeasonRankSummary
from ironsbot.services.seer.sequ_extra import UnityPeakInfo

if TYPE_CHECKING:
    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.services.operations.headless import HeadlessGame
    from ironsbot.services.seer.player_profile_cache import PlayerProfileCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _UnavailableOnlineInfo:
    unavailable: bool = True


@dataclass(frozen=True, slots=True)
class _CachedMoreInfo:
    user_id: int
    nick: str
    reg_time: int


async def fetch_pending_player_query(
    config: SeerConfig,
    player_id: int,
    game: HeadlessGame,
    *,
    group_id: int | None,
    profile_cache: PlayerProfileCache,
) -> PendingPlayerQuery:
    extra_errors: list[str] = []
    plan = plan_player_query_sections(
        config.player.sections,
        local_rank_enabled=config.local_rank.enabled,
    )

    async def fetch_user_info() -> Any:
        with game.operations.track(
            "基础资料",
            f"米米号 {player_id}",
            source="米米号查询",
            group_id=group_id,
        ):
            return await game.get_user_info(player_id)

    user_info = await asyncio.wait_for(
        fetch_user_info(),
        timeout=config.player.timeout_seconds,
    )
    cached_reg_time = profile_cache.registration_time(player_id)

    async def fetch_more_info() -> Any:
        if cached_reg_time is not None:
            return _CachedMoreInfo(
                user_id=player_id,
                nick=str(user_info.nick),
                reg_time=cached_reg_time,
            )
        with game.operations.track(
            "补充资料",
            f"米米号 {player_id}",
            source="米米号查询",
            group_id=group_id,
        ):
            result = await game.get_more_user_info(player_id)
        profile_cache.upsert_registration_time(
            player_id=player_id,
            nick=str(user_info.nick),
            reg_time=int(getattr(result, "reg_time", 0) or 0),
        )
        return result

    async def fetch_online_info() -> Any:
        if not plan.needs_online_info:
            return None
        with game.operations.track(
            "在线状态",
            f"米米号 {player_id}",
            source="米米号查询",
            group_id=group_id,
        ):
            return await optional_player_extra(
                label="在线状态",
                enabled=True,
                awaitable_factory=lambda: game.get_user_online_info(player_id),
                default=_UnavailableOnlineInfo(),
                extra_errors=extra_errors,
                on_error=_log_player_extra_error,
            )

    async def fetch_team_name() -> str:
        if getattr(user_info, "team_id", 0) <= 0:
            return "无"
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
            return str(team_info.name)
        except Exception:
            logger.exception("米米号基础字段获取失败：战队资料")
            extra_errors.append("战队资料暂未获取")
            return "暂未获取"

    more_info, online_info, team_name = await asyncio.wait_for(
        asyncio.gather(
            fetch_more_info(),
            fetch_online_info(),
            fetch_team_name(),
        ),
        timeout=config.player.timeout_seconds,
    )
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
        base_snapshot=PlayerBaseSnapshot(
            player_id=player_id,
            user_info=user_info,
            more_info=more_info,
            online_info=online_info,
            team_name=team_name,
        ),
    )


def _log_player_extra_error(label: str, _error: Exception) -> None:
    logger.exception("米米号基础字段获取失败：%s", label)
