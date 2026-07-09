# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

from ironsbot.services.ai.intent import (
    get_team_resource_config,
)
from ironsbot.services.team_resource_adapter import (
    fetch_team_resource_result,
)
from ironsbot.shared.messaging import finish_event_reply, finish_message_sequence
from ironsbot.shared.plugin_system import PluginContext, register_plugin

if TYPE_CHECKING:
    from ironsbot.config.models.ai import AiIntentAction

TEAM_RECOMMEND_PLUGIN_NAME = "team_recommend"

__plugin_meta__ = PluginMetadata(
    name="战队推荐",
    description="发送配置好的战队审核群链接或战队推荐信息。",
    usage=(
        "【战队推荐】\n"
        "此功能不直接匹配口令，通常由配置化意图动作调用。\n"
        "回复内容、触发条件和目标战队以当前配置为准。"
    ),
)


async def _handle_team_recommend_action(
    action: AiIntentAction,
    event: MessageEvent,
    context: PluginContext,
) -> None:
    if context.matcher is None:
        return

    await finish_event_reply(
        context.matcher,
        event,
        action.message,
        mention_sender=True,
    )


async def _handle_team_resource_action(
    action: AiIntentAction,
    event: MessageEvent,
    context: PluginContext,
) -> None:
    if context.matcher is None:
        return

    team_ids = action.team_ids
    if not team_ids:
        await finish_event_reply(
            context.matcher,
            event,
            "这个 AI 战队动作还没有配置 team_ids。",
            mention_sender=True,
        )

    replies: list[Message] = []
    for team_id in team_ids:
        try:
            result = await asyncio.wait_for(
                fetch_team_resource_result(team_id),
                timeout=get_team_resource_config().query_timeout_seconds,
            )
        except FinishedException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(
                f"Team recommend resource action query failed, team id {team_id}: {e}"
            )
            replies.append(Message(f"战队 {team_id} 查询失败，请稍后再试。"))
            continue

        replies.append(Message(result.message))

    if not replies:
        return

    await finish_message_sequence(context.matcher, replies, event=event)


class TeamRecommendPlugin:
    name = TEAM_RECOMMEND_PLUGIN_NAME
    feature = "ai_intent"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        action = context.data["ai_action"]
        if action.action == "team_resource":
            await _handle_team_resource_action(action, event, context)
            return

        await _handle_team_recommend_action(action, event, context)


register_plugin(TeamRecommendPlugin())


__all__ = ["TEAM_RECOMMEND_PLUGIN_NAME", "TeamRecommendPlugin"]
