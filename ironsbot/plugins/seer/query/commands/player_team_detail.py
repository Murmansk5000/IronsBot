# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.onebot_context import event_group_id
from ironsbot.runtime.permissions import can_manage_group_event
from ironsbot.services.seer.team import TeamQueryActor

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import MessageEvent

    from ironsbot.core.features import FeatureService

    from .player_context import PlayerDetailMenuContext


def player_team_menu_text(
    features: FeatureService,
    event: Event,
    context: PlayerDetailMenuContext,
) -> str | None:
    snapshot = context.base_snapshot
    if (
        snapshot is None
        or context.team_query is None
        or not event_is_feature_allowed(features, event, "seer_team")
    ):
        return None
    team_id = int(getattr(snapshot.user_info, "team_id", 0) or 0)
    if team_id <= 0:
        return None
    team_name = snapshot.team_name.strip() or "未知战队"
    return f"{team_name}（战队ID：{team_id}）"


async def query_player_team_detail(
    context: PlayerDetailMenuContext,
    features: FeatureService,
    event: MessageEvent,
) -> str | None:
    snapshot = context.base_snapshot
    if context.team_query is None or snapshot is None:
        return None
    team_id = int(getattr(snapshot.user_info, "team_id", 0) or 0)
    if team_id <= 0:
        return None
    return await context.team_query.query(
        (team_id,),
        TeamQueryActor(
            user_id=event.user_id,
            group_id=event_group_id(event),
            can_manage=can_manage_group_event(features, event),
        ),
    )
