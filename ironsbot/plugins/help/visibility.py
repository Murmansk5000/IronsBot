# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.shared.features.service import is_superuser
from ironsbot.shared.features.visibility import feature_visible_for_help

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.config.models.app import AppConfig
    from ironsbot.runtime.plugins import PluginDefinition


def _any_feature_visible(
    event: Event,
    definition: PluginDefinition,
) -> bool:
    return any(
        feature_visible_for_help(event, feature.value)
        for feature in definition.features
    )


def _messaging_visible(event: Event, config: AppConfig) -> bool:
    msg_config = config.message
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


def _superuser_visible(event: Event) -> bool:
    user_id = getattr(event, "user_id", None)
    return user_id is not None and is_superuser(int(user_id))


def plugin_visible_for_event(
    definition: PluginDefinition,
    event: Event,
    *,
    config: AppConfig,
    ai_key_configured: bool,
) -> bool:
    help_entry = definition.help
    if help_entry is None or help_entry.visibility == "hidden":
        visible = False
    elif help_entry.visibility == "always":
        visible = True
    elif definition.id == "messaging":
        visible = _messaging_visible(event, config)
    elif definition.id == "team_resource":
        visible = (
            config.seer.team_resource.enabled
            and isinstance(event, GroupMessageEvent)
            and feature_visible_for_help(event, "team_resource_subscription")
        )
    elif definition.id == "ai_chat":
        visible = ai_key_configured and feature_visible_for_help(event, "ai_chat")
    elif definition.id == "ai_intent":
        visible = (
            ai_key_configured
            and config.ai.intent_actions_enabled
            and feature_visible_for_help(event, "ai_intent")
        )
    elif definition.id == "headless_notice":
        visible = _superuser_visible(event)
    else:
        visible = _any_feature_visible(event, definition)
    return visible


__all__ = ["plugin_visible_for_event"]
