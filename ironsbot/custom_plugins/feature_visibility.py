# SPDX-License-Identifier: MIT
import json

from nonebot import get_plugin_config
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.feature_policy import (
    is_event_feature_allowed,
    is_group_feature_allowed,
    is_private_feature_allowed,
    is_superuser,
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


def _coerce_model_list(value: object) -> object:
    if value is None or value == "":
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)

    return value


class VisibilityMessageAction(BaseModel):
    enabled: bool = True
    feature: str = "text"

    @field_validator("feature")
    @classmethod
    def normalize_feature(cls, value: str) -> str:
        feature = value.strip()
        return feature or "text"


class VisibilityMessageSchedule(VisibilityMessageAction):
    feature: str = "text_push"


class VisibilityConfig(BaseModel):
    ai_key: str = ""
    ai_intent_actions_enabled: bool = True
    msg_private_commands: list[VisibilityMessageAction] = Field(default_factory=list)
    msg_private_schedules: list[VisibilityMessageSchedule] = Field(default_factory=list)
    msg_group_commands: list[VisibilityMessageAction] = Field(default_factory=list)
    msg_group_schedules: list[VisibilityMessageSchedule] = Field(default_factory=list)
    team_ids: list[int] = Field(default_factory=list)

    @field_validator(
        "msg_private_commands",
        "msg_private_schedules",
        "msg_group_commands",
        "msg_group_schedules",
        mode="before",
    )
    @classmethod
    def normalize_model_list(cls, value: object) -> object:
        return _coerce_model_list(value)

    @field_validator("team_ids", mode="before")
    @classmethod
    def normalize_int_list(cls, value: object) -> object:
        if value is None or value == "":
            return []
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                return json.loads(text)
            return [
                int(item.strip())
                for item in text.split(",")
                if item.strip()
            ]
        return value


visibility_config = get_plugin_config(VisibilityConfig)


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
                *visibility_config.msg_group_commands,
                *visibility_config.msg_group_schedules,
            ]
        )

    if isinstance(event, PrivateMessageEvent):
        return any(
            action.enabled
            and is_private_feature_allowed(event.user_id, action.feature)
            for action in [
                *visibility_config.msg_private_commands,
                *visibility_config.msg_private_schedules,
            ]
        )

    return False


def _team_shortcut_visible(event: Event) -> bool:
    return (
        bool(visibility_config.team_ids)
        and isinstance(event, GroupMessageEvent)
        and is_group_feature_allowed(event.user_id, event.group_id, "team")
    )


def _ai_chat_visible(event: Event) -> bool:
    return bool(visibility_config.ai_key) and _feature_visible(event, "ai")


def _ai_intent_visible(event: Event) -> bool:
    return (
        bool(visibility_config.ai_key)
        and visibility_config.ai_intent_actions_enabled
        and _feature_visible(event, "ai_intent")
    )


def _superuser_visible(event: Event) -> bool:
    user_id = getattr(event, "user_id", None)
    return user_id is not None and is_superuser(int(user_id))


def plugin_visible_for_event(  # noqa: C901, PLR0911
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

    if module_name.startswith("ironsbot.custom_plugins.message_actions"):
        return _message_actions_visible(event)

    if module_name.startswith("ironsbot.custom_plugins.team_shortcut"):
        return _team_shortcut_visible(event)

    if module_name.startswith("ironsbot.custom_plugins.ai_chat"):
        return _ai_chat_visible(event)

    if module_name.startswith("ironsbot.custom_plugins.ai_intent_actions"):
        return _ai_intent_visible(event)

    if module_name.startswith("ironsbot.custom_plugins.headless_seer_notice"):
        return _superuser_visible(event)

    for module_prefix, features in FEATURE_MODULE_PREFIXES:
        if module_name.startswith(module_prefix):
            return _any_feature_visible(event, features)

    return False
