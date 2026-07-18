# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from nonebot import get_driver
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.config.loader import get_app_config, load_secrets_config
from ironsbot.shared.features.service import is_superuser
from ironsbot.shared.features.visibility import feature_visible_for_help

if TYPE_CHECKING:
    from ironsbot.runtime.plugins import PluginDefinition

VisibilityRule = Callable[[Event], bool]


def _any_feature_visible(
    event: Event,
    definition: PluginDefinition,
) -> bool:
    return any(
        feature_visible_for_help(event, feature.value)
        for feature in definition.features
    )


def _ai_key_configured() -> bool:
    if load_secrets_config().ai_key.strip():
        return True

    try:
        return bool(str(getattr(get_driver().config, "ai_key", "") or "").strip())
    except ValueError:
        return False


def _messaging_visible(event: Event) -> bool:
    msg_config = get_app_config().message
    if isinstance(event, GroupMessageEvent):
        actions = [*msg_config.group_commands, *msg_config.group_schedules]
    elif isinstance(event, PrivateMessageEvent):
        actions = [*msg_config.private_commands, *msg_config.private_schedules]
    else:
        return False
    return any(
        action.enabled and feature_visible_for_help(event, action.feature)
        for action in actions
    )


def _team_resource_visible(event: Event) -> bool:
    return (
        get_app_config().seer.team_resource.enabled
        and isinstance(event, GroupMessageEvent)
        and feature_visible_for_help(event, "team_resource_subscription")
    )


def _ai_chat_visible(event: Event) -> bool:
    return _ai_key_configured() and feature_visible_for_help(event, "ai_chat")


def _ai_intent_visible(event: Event) -> bool:
    return (
        _ai_key_configured()
        and get_app_config().ai.intent_actions_enabled
        and feature_visible_for_help(event, "ai_intent")
    )


def _superuser_visible(event: Event) -> bool:
    user_id = getattr(event, "user_id", None)
    return user_id is not None and is_superuser(int(user_id))


SPECIAL_VISIBILITY: dict[str, VisibilityRule] = {
    "messaging": _messaging_visible,
    "team_resource": _team_resource_visible,
    "ai_chat": _ai_chat_visible,
    "ai_intent": _ai_intent_visible,
    "headless_notice": _superuser_visible,
}


def plugin_visible_for_event(
    definition: PluginDefinition,
    event: Event,
) -> bool:
    help_entry = definition.help
    if help_entry is None or help_entry.visibility == "hidden":
        return False
    if help_entry.visibility == "always":
        return True
    if visible := SPECIAL_VISIBILITY.get(definition.id):
        return visible(event)
    return _any_feature_visible(event, definition)


__all__ = ["plugin_visible_for_event"]
