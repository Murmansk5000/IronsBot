from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from ironsbot.custom_plugins.feature_policy import (
    is_group_feature_allowed,
    is_private_feature_allowed,
)

from .constants import RESERVED_PRIVATE_COMMANDS


def is_reserved_private_command(event: MessageEvent, prompt: str) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    normalized = "".join(prompt.split()).lower().lstrip("/")
    return normalized in RESERVED_PRIVATE_COMMANDS


def is_allowed(event: MessageEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_feature_allowed(
            event.user_id,
            event.group_id,
            "ai",
        )

    if isinstance(event, PrivateMessageEvent):
        return is_private_feature_allowed(
            event.user_id,
            "ai",
        )

    return False
