# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageEvent

from ironsbot.runtime.replies import finish_event_reply, finish_message_sequence

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

    from ironsbot.core.messaging import AiIntentAction
    from ironsbot.services.team.resource import TeamResourceService

async def _handle_team_recommend_action(
    matcher: Matcher,
    action: AiIntentAction,
    event: MessageEvent,
) -> None:
    await finish_message_sequence(
        matcher,
        action.messages,
        event=event,
    )


async def _handle_team_resource_action(
    matcher: Matcher,
    action: AiIntentAction,
    event: MessageEvent,
    team_resource: TeamResourceService,
) -> None:
    team_ids = action.team_ids
    if not team_ids:
        await finish_event_reply(
            matcher,
            event,
            "这个 AI 战队动作还没有配置 team_ids。",
        )

    replies = [
        Message(message)
        for message in await team_resource.query_messages(team_ids)
    ]

    if not replies:
        return

    await finish_message_sequence(matcher, replies, event=event)


async def run_team_action(
    matcher: Matcher,
    event: MessageEvent,
    action: AiIntentAction,
    team_resource: TeamResourceService,
) -> None:
    if action.action == "team_resource":
        await _handle_team_resource_action(
            matcher,
            action,
            event,
            team_resource,
        )
        return

    await _handle_team_recommend_action(matcher, action, event)
