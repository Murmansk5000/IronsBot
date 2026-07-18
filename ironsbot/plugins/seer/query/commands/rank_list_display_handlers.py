# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from ironsbot.shared.messaging import finish_event_reply
from ironsbot.shared.permissions import can_manage_group_event

from .rank_list_context import RANK_DISPLAY_LIMIT_COMMAND_KEY

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.services.seer.rank_display import RankDisplayLimitCommand
    from ironsbot.services.seer.resources import SeerQueryResources


async def handle_display_limit(
    resources: SeerQueryResources,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command: RankDisplayLimitCommand = state[RANK_DISPLAY_LIMIT_COMMAND_KEY]
    if not isinstance(event, GroupMessageEvent):
        await finish_event_reply(matcher, event, "❌ 这个设置只能在群聊中修改。")
        return

    if not can_manage_group_event(resources.features, event):
        await finish_event_reply(
            matcher,
            event,
            "❌ 只有本群群主、管理员或超级管理员可以修改榜单默认显示条数。",
        )
        return

    max_display_limit = resources.rank_display.config.max_display_limit
    if command.limit < 1 or command.limit > max_display_limit:
        await finish_event_reply(
            matcher,
            event,
            (
                f"❌ 榜单默认显示条数必须在 1~{max_display_limit} 之间，"
                f"当前输入：{command.limit}。"
            ),
        )
        return

    resources.rank_display.set_group_limit(
        int(event.group_id),
        int(event.user_id),
        command.limit,
    )
    await finish_event_reply(
        matcher,
        event,
        f"✅ 本群榜单默认显示条数已设置为 {command.limit} 名"
        f"（群号：{int(event.group_id)}）。",
    )
