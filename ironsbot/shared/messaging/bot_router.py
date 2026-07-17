# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import get_bot, get_bots
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from ironsbot.config.loader import get_app_config

from .targets import MessageTarget

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.config.models.runtime import BotReference, BotRoutingConfig


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


def resolve_bot_id(reference: BotReference | None) -> int | None:
    if reference is None:
        return None
    return get_app_config().runtime.bot_routing.resolve_bot_reference(reference)


def _configured_target_bot_id(
    target: MessageTarget,
    config: BotRoutingConfig,
) -> int | None:
    if target.target_type == "group":
        routes = config.groups
        aliases = get_app_config().feature.group_aliases
    else:
        routes = config.users
        aliases = get_app_config().feature.user_aliases

    for target_ref, bot_ref in routes.items():
        if _resolve_target_id(target_ref, aliases) == target.target_id:
            return config.resolve_bot_reference(bot_ref)
    return None


def _legacy_default_bot(connected: Mapping[int, Bot]) -> Bot | None:
    try:
        bot = get_bot()
    except Exception:  # noqa: BLE001
        bot = None
    if isinstance(bot, Bot):
        return bot
    return next(iter(connected.values()), None)


def get_default_bot() -> Bot | None:
    config = get_app_config().runtime.bot_routing
    connected = _connected_onebot_bots()
    if not config.enabled:
        return _legacy_default_bot(connected)

    default_bot_id = (
        config.resolve_bot_reference(config.default_bot)
        if config.default_bot is not None
        else None
    )
    if default_bot_id is not None:
        if bot := connected.get(default_bot_id):
            return bot
        logger.warning(
            "configured default bot is not connected: bot_self_id={}",
            default_bot_id,
        )
    return next(iter(connected.values()), None)


def get_bot_for_target(target: MessageTarget) -> Bot | None:
    config = get_app_config().runtime.bot_routing
    if not config.enabled:
        return get_default_bot()

    connected = _connected_onebot_bots()
    routed_bot_id = _configured_target_bot_id(target, config)
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
        config.resolve_bot_reference(config.default_bot)
        if config.default_bot is not None
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


def get_bot_for_group(group_id: int) -> Bot | None:
    return get_bot_for_target(MessageTarget("group", group_id))


def get_bot_for_user(user_id: int) -> Bot | None:
    return get_bot_for_target(MessageTarget("private", user_id))


__all__ = [
    "get_bot_for_group",
    "get_bot_for_target",
    "get_bot_for_user",
    "get_default_bot",
    "resolve_bot_id",
]
