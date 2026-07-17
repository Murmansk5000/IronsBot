# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable

from nonebot import get_driver
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.config.loader import get_app_config, load_secrets_config
from ironsbot.plugin_catalog import (
    features_for_plugin_module,
    help_visibility_for_module,
)
from ironsbot.shared.features.service import is_superuser
from ironsbot.shared.features.visibility import feature_visible_for_help

VisibilityRule = Callable[[Event], bool]

def _any_feature_visible(event: Event, features: tuple[str, ...]) -> bool:
    return any(feature_visible_for_help(event, feature) for feature in features)


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
        return any(
            action.enabled
            and feature_visible_for_help(event, action.feature)
            for action in [
                *msg_config.group_commands,
                *msg_config.group_schedules,
            ]
        )

    if isinstance(event, PrivateMessageEvent):
        return any(
            action.enabled
            and feature_visible_for_help(event, action.feature)
            for action in [
                *msg_config.private_commands,
                *msg_config.private_schedules,
            ]
        )

    return False


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


SPECIAL_MODULE_VISIBILITY: tuple[tuple[str, VisibilityRule], ...] = (
    ("ironsbot.plugins.messaging", _messaging_visible),
    ("ironsbot.plugins.team_resource_subscription", _team_resource_visible),
    ("ironsbot.plugins.ai_chat", _ai_chat_visible),
    ("ironsbot.plugins.ai_intent", _ai_intent_visible),
    ("ironsbot.plugins.headless_seer_notice", _superuser_visible),
)


def _visible_by_special_rule(module_name: str, event: Event) -> bool | None:
    for module_prefix, visible in SPECIAL_MODULE_VISIBILITY:
        if module_name.startswith(module_prefix):
            return visible(event)
    return None


def _visible_by_feature_rule(module_name: str, event: Event) -> bool | None:
    features = features_for_plugin_module(module_name)
    if features:
        return _any_feature_visible(event, features)
    return None


def plugin_visible_for_event(
    _plugin_name: str,
    module_name: str,
    event: Event,
) -> bool:
    static_visibility = help_visibility_for_module(module_name)
    if static_visibility == "hidden":
        return False

    if static_visibility == "always":
        return True

    if (visible := _visible_by_special_rule(module_name, event)) is not None:
        return visible

    if (visible := _visible_by_feature_rule(module_name, event)) is not None:
        return visible

    return False


__all__ = [
    "features_for_plugin_module",
    "plugin_visible_for_event",
]
