# SPDX-License-Identifier: MIT
"""Platform-neutral execution of classified AI intent actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.core.messaging import AiIntentAction
    from ironsbot.core.promotions import PromotionCatalog
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.team.resource import TeamResourceService


class AiIntentActionExecutor:
    def __init__(
        self,
        ai: AiService,
        promotions: PromotionCatalog,
        team_resources: TeamResourceService,
    ) -> None:
        self._ai = ai
        self._promotions = promotions
        self._team_resources = team_resources

    async def execute(
        self,
        action: AiIntentAction,
        text: str,
        *,
        source_context: str | None = None,
    ) -> tuple[OutboundMessage, ...]:
        if action.action == "team_recommend":
            return _text_messages(action.messages)
        if action.action == "team_resource":
            if not action.team_ids:
                return _text_messages(("这个 AI 战队动作还没有配置 team_ids。",))
            return _text_messages(
                await self._team_resources.query_messages(action.team_ids)
            )
        if action.action == "ai_reply":
            reply = await self._ai.run_reply_action(
                action,
                text,
                source_context=source_context,
            )
            return _text_messages((reply,)) if reply else ()
        if action.action == "promotion":
            return _text_messages((self._promotions.require(action.promotion).message,))
        return _text_messages((action.message,))


def _text_messages(messages: Iterable[str]) -> tuple[OutboundMessage, ...]:
    return tuple(
        OutboundMessage.from_text(message)
        for message in messages
        if isinstance(message, str) and message
    )
