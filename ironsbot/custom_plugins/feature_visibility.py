import json

from nonebot import get_plugin_config
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.superuser_policy import (
    get_custom_push_groups,
    get_custom_push_users,
    is_custom_feature_event_allowed,
    is_group_allowed_for_user,
    is_private_user_allowed,
    is_superuser,
    with_custom_push_groups,
    with_custom_push_users,
    with_superuser_groups,
    with_superusers,
)


def _coerce_int_list(value: object) -> object:
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


class VisibilityAiIntentAction(BaseModel):
    enabled: bool = True
    group_ids: list[int] = Field(default_factory=list)
    user_ids: list[int] = Field(default_factory=list)
    action: str = "team_shortcut"

    @field_validator("group_ids", "user_ids", mode="before")
    @classmethod
    def normalize_int_list(cls, value: object) -> object:
        return _coerce_int_list(value)


class VisibilityPrivateCommand(BaseModel):
    enabled: bool = True
    allowed_user_ids: list[int] = Field(default_factory=list)

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def normalize_int_list(cls, value: object) -> object:
        return _coerce_int_list(value)


class VisibilityGroupCommand(BaseModel):
    enabled: bool = True
    group_ids: list[int] = Field(default_factory=list)

    @field_validator("group_ids", mode="before")
    @classmethod
    def normalize_int_list(cls, value: object) -> object:
        return _coerce_int_list(value)


class VisibilityPrivateSchedule(BaseModel):
    enabled: bool = True
    user_ids: list[int] = Field(default_factory=list)

    @field_validator("user_ids", mode="before")
    @classmethod
    def normalize_int_list(cls, value: object) -> object:
        return _coerce_int_list(value)


class VisibilityGroupSchedule(BaseModel):
    enabled: bool = True
    group_ids: list[int] = Field(default_factory=list)

    @field_validator("group_ids", mode="before")
    @classmethod
    def normalize_int_list(cls, value: object) -> object:
        return _coerce_int_list(value)


def _default_ai_intent_actions() -> list[VisibilityAiIntentAction]:
    return [VisibilityAiIntentAction(action="team_shortcut")]


class VisibilityConfig(BaseModel):
    ai_key: str = ""
    ai_groups: list[int] = Field(default_factory=list)
    ai_users: list[int] = Field(default_factory=list)
    ai_intent_actions_enabled: bool = True
    ai_intent_actions: list[VisibilityAiIntentAction] = Field(
        default_factory=_default_ai_intent_actions
    )
    activity_reminder_groups: list[int] = Field(default_factory=list)
    activity_reminder_users: list[int] = Field(default_factory=list)
    meeting_groups: list[int] = Field(default_factory=list)
    meeting_users: list[int] = Field(default_factory=list)
    msg_private_commands: list[VisibilityPrivateCommand] = Field(default_factory=list)
    msg_private_schedules: list[VisibilityPrivateSchedule] = Field(default_factory=list)
    msg_group_commands: list[VisibilityGroupCommand] = Field(default_factory=list)
    msg_group_schedules: list[VisibilityGroupSchedule] = Field(default_factory=list)
    team_groups: list[int] = Field(default_factory=list)
    team_ids: list[int] = Field(default_factory=list)

    @field_validator(
        "ai_groups",
        "ai_users",
        "activity_reminder_groups",
        "activity_reminder_users",
        "meeting_groups",
        "meeting_users",
        "team_groups",
        "team_ids",
        mode="before",
    )
    @classmethod
    def normalize_int_list(cls, value: object) -> object:
        return _coerce_int_list(value)

    @field_validator(
        "ai_intent_actions",
        "msg_private_commands",
        "msg_private_schedules",
        "msg_group_commands",
        "msg_group_schedules",
        mode="before",
    )
    @classmethod
    def normalize_model_list(cls, value: object) -> object:
        parsed = _coerce_model_list(value)
        if parsed == [] and value in (None, ""):
            return parsed
        return parsed


visibility_config = get_plugin_config(VisibilityConfig)

ALWAYS_VISIBLE_NAMES = frozenset({"帮助", "关于"})
CUSTOM_FEATURE_NAMES = frozenset(
    {
        "扩展赛尔号查询",
        "榜单",
        "图片发送",
    }
)
INTERNAL_PLUGIN_NAMES = frozenset(
    {
        "AI @ 提示拦截",
        "HTTP 缓存客户端",
        "赛尔号数据",
        "赛尔号信息查询",
        "发图",
        "超级管理员优先级",
        "定时重启",
    }
)
ORIGINAL_PLUGIN_MODULE_PREFIXES = (
    "ironsbot.plugins.about",
    "ironsbot.plugins.help",
)


def custom_feature_visible(event: Event) -> bool:
    return is_custom_feature_event_allowed(event)


def plugin_visible_for_event(  # noqa: C901, PLR0911, PLR0912
    plugin_name: str,
    module_name: str,
    event: Event,
) -> bool:
    if module_name.startswith(ORIGINAL_PLUGIN_MODULE_PREFIXES):
        return False

    if plugin_name in INTERNAL_PLUGIN_NAMES:
        return False

    if plugin_name in ALWAYS_VISIBLE_NAMES:
        return True

    if plugin_name in CUSTOM_FEATURE_NAMES:
        return custom_feature_visible(event)

    if plugin_name == "B站动态":
        return _bili_visible(event)

    if plugin_name == "AI聊天":
        return _ai_chat_visible(event)

    if plugin_name == "AI意图动作":
        return _ai_intent_visible(event)

    if plugin_name == "活动结束提醒":
        return _activity_visible(event)

    if plugin_name == "文本发送":
        return _message_actions_visible(event)

    if plugin_name == "会议回复":
        return _meeting_visible(event)

    if plugin_name == "战队快捷":
        return _team_shortcut_visible(event)

    if plugin_name == "开服查询":
        return _server_status_visible(event)

    if plugin_name == "自定义无头登录":
        return _superuser_visible(event)

    return False


def _bili_visible(event: Event) -> bool:
    return isinstance(event, (GroupMessageEvent, PrivateMessageEvent)) and (
        is_custom_feature_event_allowed(event)
    )


def _ai_chat_allowed(event: Event) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_allowed_for_user(
            event.user_id,
            event.group_id,
            visibility_config.ai_groups,
        )

    if isinstance(event, PrivateMessageEvent):
        return is_private_user_allowed(event.user_id, visibility_config.ai_users)

    return False


def _ai_chat_visible(event: Event) -> bool:
    return isinstance(event, (GroupMessageEvent, PrivateMessageEvent)) and (
        bool(visibility_config.ai_key) and _ai_chat_allowed(event)
    )


def _ai_intent_visible(event: Event) -> bool:
    if (
        not isinstance(event, (GroupMessageEvent, PrivateMessageEvent))
        or not visibility_config.ai_intent_actions_enabled
        or not visibility_config.ai_key
    ):
        return False

    return any(
        action.enabled and _ai_intent_action_visible(event, action)
        for action in visibility_config.ai_intent_actions
    )


def _ai_intent_action_visible(
    event: Event,
    action: VisibilityAiIntentAction,
) -> bool:
    if isinstance(event, GroupMessageEvent):
        group_ids = action.group_ids or (
            visibility_config.team_groups
            if action.action == "team_shortcut"
            else []
        )
        return is_group_allowed_for_user(event.user_id, event.group_id, group_ids)

    if isinstance(event, PrivateMessageEvent):
        return is_private_user_allowed(event.user_id, action.user_ids)

    return False


def _activity_visible(event: Event) -> bool:
    if isinstance(event, GroupMessageEvent):
        return (
            is_custom_feature_event_allowed(event)
            or event.group_id in with_superuser_groups(
                visibility_config.activity_reminder_groups
            )
            or event.group_id in get_custom_push_groups()
            or is_superuser(event.user_id)
        )

    if isinstance(event, PrivateMessageEvent):
        return (
            is_private_user_allowed(
                event.user_id,
                visibility_config.activity_reminder_users,
            )
            or event.user_id in get_custom_push_users()
            or is_superuser(event.user_id)
        )

    return False


def _message_actions_visible(event: Event) -> bool:
    if isinstance(event, GroupMessageEvent):
        return any(
            action.enabled
            and is_group_allowed_for_user(
                event.user_id,
                event.group_id,
                action.group_ids,
            )
            for action in visibility_config.msg_group_commands
        ) or event.group_id in {
            group_id
            for action in visibility_config.msg_group_schedules
            if action.enabled
            for group_id in with_custom_push_groups(
                with_superuser_groups(action.group_ids)
            )
        }

    if isinstance(event, PrivateMessageEvent):
        return any(
            action.enabled
            and is_private_user_allowed(event.user_id, action.allowed_user_ids)
            for action in visibility_config.msg_private_commands
        ) or event.user_id in {
            user_id
            for action in visibility_config.msg_private_schedules
            if action.enabled
            for user_id in with_custom_push_users(with_superusers(action.user_ids))
        }

    return False


def _meeting_visible(event: Event) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_allowed_for_user(
            event.user_id,
            event.group_id,
            visibility_config.meeting_groups,
        )

    if isinstance(event, PrivateMessageEvent):
        return is_private_user_allowed(event.user_id, visibility_config.meeting_users)

    return False


def _team_shortcut_visible(event: Event) -> bool:
    return (
        isinstance(event, GroupMessageEvent)
        and bool(visibility_config.team_ids)
        and is_group_allowed_for_user(
            event.user_id,
            event.group_id,
            visibility_config.team_groups,
        )
    )


def _server_status_visible(event: Event) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_custom_feature_event_allowed(event) or is_superuser(event.user_id)

    if isinstance(event, PrivateMessageEvent):
        return is_custom_feature_event_allowed(event) or is_superuser(event.user_id)

    return False


def _superuser_visible(event: Event) -> bool:
    if isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
        return is_superuser(event.user_id)
    return False
