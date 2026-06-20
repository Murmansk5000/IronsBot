# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

from ironsbot.plugins.team_shortcut.adapter import fetch_team_shortcut_result
from ironsbot.services.ai.intent import (
    get_team_ids,
    get_team_resource_users,
    get_team_shortcut_config,
)
from ironsbot.shared.messaging import finish_event_reply, finish_message_sequence
from ironsbot.shared.messaging.text import build_message
from ironsbot.shared.plugin_system import PluginContext, register_plugin

if TYPE_CHECKING:
    from ironsbot.config.models.ai import AiIntentAction

TEAM_RECOMMEND_PLUGIN_NAME = "team_recommend"

__plugin_meta__ = PluginMetadata(
    name="战队推荐",
    description="AI 判断用户想加入战队后，发送战队审核群链接或战队推荐信息。",
    usage=(
        "【战队推荐】\n"
        "此功能不直接匹配口令，由 AI意图分析 调用。\n"
        "默认在用户提到想加入战队时，发送 5 级战队审核群链接。"
    ),
)


def _build_resource_notice() -> Message:
    config = get_team_shortcut_config()
    return build_message(
        config.resource_message,
        at_user_ids=get_team_resource_users(),
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


async def _handle_team_shortcut_action(
    action: AiIntentAction,
    event: MessageEvent,
    context: PluginContext,
) -> None:
    if context.matcher is None:
        return

    team_ids = action.team_ids or get_team_ids()
    if not team_ids:
        await finish_event_reply(
            context.matcher,
            event,
            "战队信息还没有配置 seer.team_shortcut.team_ids。",
            mention_sender=True,
        )

    replies: list[Message] = []
    resource_notice_needed = False
    for team_id in team_ids:
        try:
            result = await asyncio.wait_for(
                fetch_team_shortcut_result(team_id),
                timeout=get_team_shortcut_config().query_timeout_seconds,
            )
        except FinishedException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(
                f"Team recommend shortcut action query failed, team id {team_id}: {e}"
            )
            replies.append(Message(f"战队 {team_id} 查询失败，请稍后再试。"))
            continue

        replies.append(Message(result.message))
        if result.resource < get_team_shortcut_config().resource_threshold:
            resource_notice_needed = True

    if not replies:
        return

    if action.include_team_resource_notice and resource_notice_needed:
        replies.append(_build_resource_notice())

    await finish_message_sequence(context.matcher, replies, event=event)


class TeamRecommendPlugin:
    name = TEAM_RECOMMEND_PLUGIN_NAME
    feature = "ai_intent"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        action = context.data["ai_action"]
        if action.action == "team_shortcut":
            await _handle_team_shortcut_action(action, event, context)
            return

        await _handle_team_recommend_action(action, event, context)


register_plugin(TeamRecommendPlugin())


__all__ = ["TEAM_RECOMMEND_PLUGIN_NAME", "TeamRecommendPlugin"]
