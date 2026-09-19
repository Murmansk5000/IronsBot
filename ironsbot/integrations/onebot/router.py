# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot import get_bots
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from ironsbot.core.platform import ConversationRef, Platform, reference_digest

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import BotRoutingConfig
    from ironsbot.config.onebot_references import OneBotReferenceResolver


def _connected_onebot_bots() -> dict[int, Bot]:
    try:
        bots = get_bots().values()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"bot routing failed to list connected bots: {e}")
        return {}
    return {int(bot.self_id): bot for bot in bots if isinstance(bot, Bot)}


@dataclass(frozen=True, slots=True)
class BotRouter:
    config: BotRoutingConfig
    references: OneBotReferenceResolver

    def _configured_bot_id(self, conversation: ConversationRef) -> int | None:
        if conversation.kind == "group":
            routes = self.config.groups
            resolve = self.references.resolve_group
        else:
            routes = self.config.users
            resolve = self.references.resolve_user

        for target_ref, bot_ref in routes.items():
            if resolve(
                target_ref,
                location=f"messaging.bot_routing.{conversation.kind}s.{target_ref}",
            ) == int(conversation.id):
                return self.config.resolve_bot_reference(bot_ref)
        return None

    def default_bot(self) -> Bot | None:
        connected = _connected_onebot_bots()
        bot_id = (
            self.config.resolve_bot_reference(self.config.default_bot)
            if self.config.default_bot is not None
            else None
        )
        if bot_id is not None:
            if bot := connected.get(bot_id):
                return bot
            logger.warning(
                "configured default bot is not connected: bot_ref={}",
                reference_digest(str(bot_id)),
            )
        return None

    def for_conversation(self, conversation: ConversationRef) -> Bot | None:
        """Route one typed OneBot conversation at the integration edge."""

        if (
            conversation.platform is not Platform.ONEBOT
            or conversation.kind not in {"private", "group"}
            or not conversation.id.isdecimal()
            or int(conversation.id) <= 0
        ):
            return None
        connected = _connected_onebot_bots()
        routed_bot_id = (
            self._configured_bot_id(conversation) if self.config.enabled else None
        )
        if routed_bot_id is not None:
            if bot := connected.get(routed_bot_id):
                return bot
            logger.warning(
                "routed bot is not connected: target_type={} target_ref={} "
                "bot_ref={}; falling back to default bot",
                conversation.kind,
                reference_digest(conversation.id),
                reference_digest(str(routed_bot_id)),
            )

        default_bot_id = (
            self.config.resolve_bot_reference(self.config.default_bot)
            if self.config.default_bot is not None
            else None
        )
        if default_bot_id is not None and default_bot_id != routed_bot_id:
            if bot := connected.get(default_bot_id):
                return bot
            logger.warning(
                "default bot fallback is not connected: target_type={} target_ref={} "
                "bot_ref={}; delivery will fail",
                conversation.kind,
                reference_digest(conversation.id),
                reference_digest(str(default_bot_id)),
            )
        logger.warning(
            "no configured OneBot bot is available: target_type={} target_ref={}",
            conversation.kind,
            reference_digest(conversation.id),
        )
        return None
