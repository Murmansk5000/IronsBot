from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from ironsbot.shared.features import (
    is_group_feature_allowed,
    is_private_feature_allowed,
)
from ironsbot.shared.messaging.text import normalize_command_text

RESERVED_PRIVATE_COMMANDS = {
    "help",
    "帮助",
    "动态",
    "动态刷新",
    "动态更新",
    "刷新动态",
    "更新动态",
    "数据版本",
    "数据更新",
    "更新数据",
    "服务器状态",
    "签到",
    "活动",
    "链接",
}


def is_reserved_private_command(event: MessageEvent, prompt: str) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    normalized = normalize_command_text(prompt).lstrip("/")
    return normalized in RESERVED_PRIVATE_COMMANDS


def is_allowed(event: MessageEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_feature_allowed(
            event.user_id,
            event.group_id,
            "ai_chat",
        )

    if isinstance(event, PrivateMessageEvent):
        return is_private_feature_allowed(
            event.user_id,
            "ai_chat",
        )

    return False
