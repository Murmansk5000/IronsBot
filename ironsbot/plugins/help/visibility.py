# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable

from nonebot import get_driver
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.config.loader import get_app_config, load_secrets_config
from ironsbot.shared.features.service import is_superuser
from ironsbot.shared.features.visibility import feature_visible_for_help

FeatureModuleRegistry = dict[str, tuple[str, ...]]
VisibilityRule = Callable[[Event], bool]

FEATURE_MODULE_REGISTRY: FeatureModuleRegistry = {
    "about": ("ironsbot.plugins.about",),
    "help": ("ironsbot.plugins.help",),
    "seer": ("ironsbot.plugins.seer.query",),
    "seer_player": ("ironsbot.plugins.seer.query",),
    "seer_team": ("ironsbot.plugins.seer.query",),
    "seer_pet": ("ironsbot.plugins.seer.query",),
    "seer_mintmark": ("ironsbot.plugins.seer.query",),
    "seer_equipment": ("ironsbot.plugins.seer.query",),
    "seer_type": ("ironsbot.plugins.seer.query",),
    "seer_peak": ("ironsbot.plugins.seer.query",),
    "seer_autocard": ("ironsbot.plugins.seer.query",),
    "seer_rank": (
        "ironsbot.plugins.seer.query",
        "ironsbot.plugins.seer.rank_help",
    ),
    "seer_data": ("ironsbot.plugins.seer.query",),
    "image": ("ironsbot.plugins.sendpic",),
    "rank": ("ironsbot.plugins.seer.rank_help",),
    "meeting": ("ironsbot.plugins.meeting",),
    "text": ("ironsbot.plugins.messaging",),
    "text_push": ("ironsbot.plugins.messaging",),
    "web_activity_link": ("ironsbot.plugins.messaging",),
    "web_activity_push": ("ironsbot.plugins.messaging",),
    "seerinfo": ("ironsbot.plugins.messaging",),
    "bili_query": ("ironsbot.plugins.bilibili",),
    "bili_push": ("ironsbot.plugins.bilibili",),
    "seer_activity_query": ("ironsbot.plugins.activity",),
    "seer_activity_push": ("ironsbot.plugins.activity",),
    "server_status_query": ("ironsbot.plugins.server_status",),
    "server_status_push": ("ironsbot.plugins.server_status",),
    "team_resource_subscription": ("ironsbot.plugins.team_resource_subscription",),
    "team_audit": ("ironsbot.plugins.team_audit_welcome",),
    "ai_chat": ("ironsbot.plugins.ai_chat",),
    "ai_intent": (
        "ironsbot.plugins.ai_intent",
        "ironsbot.plugins.team_recommend",
    ),
    "fire_manual_ad": ("ironsbot.plugins.fire_manual_ad",),
    "admin_notice": ("ironsbot.plugins.ai_chat",),
}

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


def _module_startswith(module_name: str, prefixes: tuple[str, ...]) -> bool:
    return any(module_name.startswith(prefix) for prefix in prefixes)


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
        bool(get_app_config().seer.team_resource.subscriptions)
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


def features_for_plugin_module(module_name: str) -> tuple[str, ...]:
    features: list[str] = []
    for feature, modules in FEATURE_MODULE_REGISTRY.items():
        if any(module_name.startswith(module_prefix) for module_prefix in modules):
            features.append(feature)
    return tuple(features)


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
    if _module_startswith(module_name, HIDDEN_MODULE_PREFIXES):
        return False

    if _module_startswith(module_name, ALWAYS_VISIBLE_MODULE_PREFIXES):
        return True

    if (visible := _visible_by_special_rule(module_name, event)) is not None:
        return visible

    if (visible := _visible_by_feature_rule(module_name, event)) is not None:
        return visible

    return False


__all__ = [
    "FEATURE_MODULE_REGISTRY",
    "FeatureModuleRegistry",
    "features_for_plugin_module",
    "plugin_visible_for_event",
]
