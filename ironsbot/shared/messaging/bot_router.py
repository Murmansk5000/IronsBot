# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot import get_bot, get_bots
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.config.models.runtime import BotRoutingConfig

    from .targets import MessageTarget


def _resolve_target_id(reference: str, aliases: Mapping[str, int]) -> int | None:
    normalized = reference.strip()
    if normalized in aliases:
        return aliases[normalized]
    if normalized.isdigit() and int(normalized) > 0:
        return int(normalized)
    return None


def _connected_onebot_bots() -> dict[int, Bot]:
    try:
        bots = get_bots().values()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"bot routing failed to list connected bots: {e}")
        return {}
    return {
        int(bot.self_id): bot
        for bot in bots
        if isinstance(bot, Bot)
    }


def _legacy_default_bot(connected: Mapping[int, Bot]) -> Bot | None:
    try:
        bot = get_bot()
    except Exception:  # noqa: BLE001
        bot = None
    if isinstance(bot, Bot):
        return bot
    return next(iter(connected.values()), None)


@dataclass(frozen=True, slots=True)
class BotRouter:
    config: BotRoutingConfig
    group_aliases: Mapping[str, int]
    user_aliases: Mapping[str, int]

    def _configured_bot_id(self, target: MessageTarget) -> int | None:
        if target.target_type == "group":
            routes = self.config.groups
            aliases = self.group_aliases
        else:
            routes = self.config.users
            aliases = self.user_aliases

        for target_ref, bot_ref in routes.items():
            if _resolve_target_id(target_ref, aliases) == target.target_id:
                return self.config.resolve_bot_reference(bot_ref)
        return None

    def default_bot(self) -> Bot | None:
        connected = _connected_onebot_bots()
        if not self.config.enabled:
            return _legacy_default_bot(connected)

        bot_id = (
            self.config.resolve_bot_reference(self.config.default_bot)
            if self.config.default_bot is not None
            else None
        )
        if bot_id is not None:
            if bot := connected.get(bot_id):
                return bot
            logger.warning(
                "configured default bot is not connected: bot_self_id={}",
                bot_id,
            )
        return next(iter(connected.values()), None)

    def for_target(self, target: MessageTarget) -> Bot | None:
        if not self.config.enabled:
            return self.default_bot()

        connected = _connected_onebot_bots()
        routed_bot_id = self._configured_bot_id(target)
        if routed_bot_id is not None:
            if bot := connected.get(routed_bot_id):
                return bot
            logger.warning(
                "routed bot is not connected: target_type={} target_id={} "
                "bot_self_id={}; falling back to default bot",
                target.target_type,
                target.target_id,
                routed_bot_id,
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
                "default bot fallback is not connected: target_type={} target_id={} "
                "bot_self_id={}; falling back to any OneBot bot",
                target.target_type,
                target.target_id,
                default_bot_id,
            )
        return next(iter(connected.values()), None)
