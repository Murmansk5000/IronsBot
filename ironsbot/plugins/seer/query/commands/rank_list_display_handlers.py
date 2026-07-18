# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from ironsbot.services.seer.rank_display import (
    RankDisplayLimitCommand,
    build_rank_display_limit_denied_message,
    build_rank_display_limit_invalid_message,
    build_rank_display_limit_message,
    set_group_rank_display_limit,
)
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.shared.permissions import can_manage_group_event

from ..config import get_rank_query_config
from .rank_list_context import RANK_DISPLAY_LIMIT_COMMAND_KEY

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.shared.features import FeatureService


async def handle_display_limit(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    features: FeatureService,
) -> None:
    command: RankDisplayLimitCommand = state[RANK_DISPLAY_LIMIT_COMMAND_KEY]
    if not isinstance(event, GroupMessageEvent):
        await finish_event_reply(matcher, event, "❌ 这个设置只能在群聊中修改。")
        return

    if not can_manage_group_event(features, event):
        await finish_event_reply(
            matcher,
            event,
            build_rank_display_limit_denied_message(),
        )
        return

    rank_config = get_rank_query_config()
    if command.limit < 1 or command.limit > rank_config.max_display_limit:
        await finish_event_reply(
            matcher,
            event,
            build_rank_display_limit_invalid_message(command.limit),
        )
        return

    set_group_rank_display_limit(
        int(event.group_id),
        int(event.user_id),
        command.limit,
    )
    await finish_event_reply(
        matcher,
        event,
        build_rank_display_limit_message(
            group_id=int(event.group_id),
            limit=command.limit,
        ),
    )
