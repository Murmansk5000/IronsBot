# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable

from nonebot import get_driver
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.config import get_app_config, load_secrets_config
from ironsbot.shared.features.registry import features_for_module

from .service import (
    is_event_feature_allowed,
    is_group_feature_allowed,
    is_private_feature_allowed,
    is_superuser,
)

HIDDEN_MODULE_PREFIXES = (
    "ironsbot.plugins.ai_mention_guard",
    "ironsbot.plugins.scheduled_restart",
    "ironsbot.plugins.startup_notice",
    "ironsbot.plugins.admin_priority",
    "ironsbot.plugins.db_sync",
    "ironsbot.plugins.fire_manual_ad",
    "ironsbot.plugins.headless_seer",
    "ironsbot.plugins.http_client",
    "ironsbot.plugins.seer_data",
    "ironsbot.plugins.team_audit_welcome",
    "ironsbot.plugins.team_recommend",
)

ALWAYS_VISIBLE_MODULE_PREFIXES = (
    "ironsbot.plugins.about",
    "ironsbot.plugins.help",
)

VisibilityRule = Callable[[Event], bool]


def _module_startswith(module_name: str, prefixes: tuple[str, ...]) -> bool:
    return any(module_name.startswith(prefix) for prefix in prefixes)


def _feature_visible(event: Event, feature: str) -> bool:
    return is_event_feature_allowed(event, feature)


def _any_feature_visible(event: Event, features: tuple[str, ...]) -> bool:
    return any(_feature_visible(event, feature) for feature in features)


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
            and is_group_feature_allowed(event.user_id, event.group_id, action.feature)
            for action in [
                *msg_config.group_commands,
                *msg_config.group_schedules,
            ]
        )

    if isinstance(event, PrivateMessageEvent):
        return any(
            action.enabled
            and is_private_feature_allowed(event.user_id, action.feature)
            for action in [
                *msg_config.private_commands,
                *msg_config.private_schedules,
            ]
        )

    return False


def _team_shortcut_visible(event: Event) -> bool:
    return (
        bool(get_app_config().seer.team_shortcut.team_ids)
        and isinstance(event, GroupMessageEvent)
        and is_group_feature_allowed(event.user_id, event.group_id, "team")
    )


def _ai_chat_visible(event: Event) -> bool:
    return _ai_key_configured() and _feature_visible(event, "ai_chat")


def _ai_intent_visible(event: Event) -> bool:
    return (
        _ai_key_configured()
        and get_app_config().ai.intent_actions_enabled
        and _feature_visible(event, "ai_intent")
    )


def _superuser_visible(event: Event) -> bool:
    user_id = getattr(event, "user_id", None)
    return user_id is not None and is_superuser(int(user_id))


SPECIAL_MODULE_VISIBILITY: tuple[tuple[str, VisibilityRule], ...] = (
    ("ironsbot.plugins.messaging", _messaging_visible),
    ("ironsbot.plugins.team_shortcut", _team_shortcut_visible),
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
    features = features_for_module(module_name)
    if features:
        return _any_feature_visible(event, features)
    return None


def plugin_visible_for_event(
    _plugin_name: str,
    module_name: str,
    event: Event,
) -> bool:
    if _module_startswith(module_name, HIDDEN_MODULE_PREFIXES):
        return False

    if _module_startswith(module_name, ALWAYS_VISIBLE_MODULE_PREFIXES):
        return True

    if (visible := _visible_by_special_rule(module_name, event)) is not None:
        return visible

    if (visible := _visible_by_feature_rule(module_name, event)) is not None:
        return visible

    return False
