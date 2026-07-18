# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger

from ironsbot.services.ai.intent import (
    get_team_resource_config,
)
from ironsbot.services.team_resource_adapter import (
    fetch_team_resource_result,
)
from ironsbot.shared.messaging import finish_event_reply, finish_message_sequence

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

    from ironsbot.config.models.ai import AiIntentAction
    from ironsbot.integrations.headless_seer.game import SeerGame

async def _handle_team_recommend_action(
    matcher: Matcher,
    action: AiIntentAction,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        action.message,
        mention_sender=True,
    )


async def _handle_team_resource_action(
    matcher: Matcher,
    action: AiIntentAction,
    event: MessageEvent,
    game: SeerGame,
) -> None:
    team_ids = action.team_ids
    if not team_ids:
        await finish_event_reply(
            matcher,
            event,
            "这个 AI 战队动作还没有配置 team_ids。",
            mention_sender=True,
        )

    replies: list[Message] = []
    for team_id in team_ids:
        try:
            result = await asyncio.wait_for(
                fetch_team_resource_result(game, team_id),
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

    await finish_message_sequence(matcher, replies, event=event)


async def run_team_action(
    matcher: Matcher,
    event: MessageEvent,
    action: AiIntentAction,
    game: SeerGame,
) -> None:
    if action.action == "team_resource":
        await _handle_team_resource_action(matcher, action, event, game)
        return

    await _handle_team_recommend_action(matcher, action, event)


__all__ = ["run_team_action"]
