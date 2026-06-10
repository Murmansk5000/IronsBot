# SPDX-License-Identifier: MIT
from collections.abc import Callable

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.custom_plugins.ai_chat.config import plugin_config as ai_chat_config
from ironsbot.custom_plugins.feature_policy import (
    is_event_feature_allowed,
    is_group_feature_allowed,
    is_private_feature_allowed,
    is_superuser,
)
from ironsbot.custom_plugins.message_actions.config import (
    plugin_config as message_actions_config,
)
from ironsbot.custom_plugins.team_shortcut.config import (
    plugin_config as team_shortcut_config,
)

ORIGINAL_PLUGIN_MODULE_PREFIXES = (
    "ironsbot.plugins.about",
    "ironsbot.plugins.help",
)

HIDDEN_MODULE_PREFIXES = (
    "ironsbot.custom_plugins.ai_mention_guard",
    "ironsbot.custom_plugins.scheduled_restart",
    "ironsbot.custom_plugins.startup_notice",
    "ironsbot.custom_plugins.superuser_priority",
    "ironsbot.plugins.db_sync",
    "ironsbot.plugins.headless_seer",
    "ironsbot.plugins.http_client",
    "ironsbot.plugins.seer_data",
)

ALWAYS_VISIBLE_MODULE_PREFIXES = (
    "ironsbot.custom_plugins.custom_about",
    "ironsbot.custom_plugins.custom_help",
)

FEATURE_MODULE_PREFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ironsbot.custom_plugins.custom_get_seer_info", ("seer",)),
    ("ironsbot.custom_plugins.custom_sendpic", ("image",)),
    ("ironsbot.custom_plugins.rank_help", ("rank",)),
    ("ironsbot.custom_plugins.bilibili_monitor", ("bili_query", "bili_push")),
    ("ironsbot.custom_plugins.activity_reminder", ("activity_query", "activity_push")),
    ("ironsbot.custom_plugins.server_status", ("server_status_query",)),
    ("ironsbot.custom_plugins.meeting_reply", ("meeting",)),
    ("ironsbot.custom_plugins.pet_config_reply", ("seer",)),
)

VisibilityRule = Callable[[Event], bool]


def _module_startswith(module_name: str, prefixes: tuple[str, ...]) -> bool:
    return any(module_name.startswith(prefix) for prefix in prefixes)


def _feature_visible(event: Event, feature: str) -> bool:
    return is_event_feature_allowed(event, feature)


def _any_feature_visible(event: Event, features: tuple[str, ...]) -> bool:
    return any(_feature_visible(event, feature) for feature in features)


def _message_actions_visible(event: Event) -> bool:
    if isinstance(event, GroupMessageEvent):
        return any(
            action.enabled
            and is_group_feature_allowed(event.user_id, event.group_id, action.feature)
            for action in [
                *message_actions_config.msg_config.group_commands,
                *message_actions_config.msg_config.group_schedules,
            ]
        )

    if isinstance(event, PrivateMessageEvent):
        return any(
            action.enabled
            and is_private_feature_allowed(event.user_id, action.feature)
            for action in [
                *message_actions_config.msg_config.private_commands,
                *message_actions_config.msg_config.private_schedules,
            ]
        )

    return False


def _team_shortcut_visible(event: Event) -> bool:
    return (
        bool(team_shortcut_config.team_ids)
        and isinstance(event, GroupMessageEvent)
        and is_group_feature_allowed(event.user_id, event.group_id, "team")
    )


def _ai_chat_visible(event: Event) -> bool:
    return bool(ai_chat_config.ai_key) and _feature_visible(event, "ai_chat")


def _ai_intent_visible(event: Event) -> bool:
    return (
        bool(ai_chat_config.ai_key)
        and ai_chat_config.ai_config.intent_actions_enabled
        and _feature_visible(event, "ai_intent")
    )


def _superuser_visible(event: Event) -> bool:
    user_id = getattr(event, "user_id", None)
    return user_id is not None and is_superuser(int(user_id))


SPECIAL_MODULE_VISIBILITY: tuple[tuple[str, VisibilityRule], ...] = (
    ("ironsbot.custom_plugins.message_actions", _message_actions_visible),
    ("ironsbot.custom_plugins.team_shortcut", _team_shortcut_visible),
    ("ironsbot.custom_plugins.ai_chat", _ai_chat_visible),
    ("ironsbot.custom_plugins.ai_intent_actions", _ai_intent_visible),
    ("ironsbot.custom_plugins.headless_seer_notice", _superuser_visible),
)


def _visible_by_special_rule(module_name: str, event: Event) -> bool | None:
    for module_prefix, visible in SPECIAL_MODULE_VISIBILITY:
        if module_name.startswith(module_prefix):
            return visible(event)
    return None


def _visible_by_feature_rule(module_name: str, event: Event) -> bool | None:
    for module_prefix, features in FEATURE_MODULE_PREFIXES:
        if module_name.startswith(module_prefix):
            return _any_feature_visible(event, features)
    return None


def plugin_visible_for_event(
    _plugin_name: str,
    module_name: str,
    event: Event,
) -> bool:
    if _module_startswith(module_name, ORIGINAL_PLUGIN_MODULE_PREFIXES):
        return False

    if _module_startswith(module_name, HIDDEN_MODULE_PREFIXES):
        return False

    if _module_startswith(module_name, ALWAYS_VISIBLE_MODULE_PREFIXES):
        return True

    if (visible := _visible_by_special_rule(module_name, event)) is not None:
        return visible

    if (visible := _visible_by_feature_rule(module_name, event)) is not None:
        return visible

    return False
