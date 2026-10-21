# SPDX-License-Identifier: MIT
"""OneBot connection lookup after the shared policy selects an account."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot import get_bots
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from ironsbot.core.platform import reference_digest

if TYPE_CHECKING:
    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.onebot_routing import OneBotRoutingPolicy


def _connected_onebot_bots() -> dict[int, Bot]:
    try:
        bots = get_bots().values()
    except Exception as error:  # noqa: BLE001 - unavailable framework connection registry
        logger.warning(
            "bot routing failed to list connected bots: error_type={}",
            type(error).__name__,
        )
        return {}
    return {int(bot.self_id): bot for bot in bots if isinstance(bot, Bot)}


@dataclass(frozen=True, slots=True)
class BotRouter:
    policy: OneBotRoutingPolicy

    def for_conversation(self, conversation: ConversationRef) -> Bot | None:
        route = self.policy.resolve(conversation)
        if route.bot_id is None:
            logger.info(
                "OneBot target has no configured account: kind={} ref={} reason={}",
                conversation.kind,
                reference_digest(conversation.id),
                route.reason,
            )
            return None
        bot = _connected_onebot_bots().get(route.bot_id)
        if bot is None:
            logger.warning(
                "selected OneBot account is not connected: target_type={} "
                "target_ref={} bot_ref={} route={}; delivery will be skipped",
                conversation.kind,
                reference_digest(conversation.id),
                reference_digest(str(route.bot_id)),
                route.reason,
            )
        return bot
