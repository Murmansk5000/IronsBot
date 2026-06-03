from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from ironsbot.custom_plugins.superuser_policy import (
    is_group_allowed_for_user,
    is_private_user_allowed,
)

from .config import plugin_config
from .constants import RESERVED_PRIVATE_COMMANDS


def is_reserved_private_command(event: MessageEvent, prompt: str) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    normalized = "".join(prompt.split()).lower()
    return normalized in RESERVED_PRIVATE_COMMANDS


def is_allowed(event: MessageEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_allowed_for_user(
            event.user_id,
            event.group_id,
            plugin_config.ai_groups,
        )

    if isinstance(event, PrivateMessageEvent):
        return is_private_user_allowed(
            event.user_id,
            plugin_config.ai_users,
        )

    return False
