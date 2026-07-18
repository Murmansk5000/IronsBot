from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.core.commands import command_text_matches
from ironsbot.shared.features import (
    is_group_feature_allowed,
    is_private_feature_allowed,
)
from ironsbot.shared.permissions import can_manage_group_event

from .config import get_message_config
from .push_management_runtime import (
    PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS,
    PUSH_TIME_COMMANDS,
)
from .runtime_service import find_command_action

if TYPE_CHECKING:
    from ironsbot.config.models.message import PrivateCommandMessageAction

PRIVATE_ACTION_KEY = "_message_action_private"
GROUP_ACTION_KEY = "_message_action_group"


def private_action_allowed(
    event: PrivateMessageEvent,
    action: PrivateCommandMessageAction,
) -> bool:
    return is_private_feature_allowed(
        event.user_id,
        action.feature,
    )


async def match_private_command(event: MessageEvent, state: T_State) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    text = event.get_plaintext()
    config = get_message_config()
    action = find_command_action(
        text,
        config.private_commands,
        is_allowed=lambda candidate: private_action_allowed(event, candidate),
    )
    if action is not None:
        state[PRIVATE_ACTION_KEY] = action
        return True

    return False


async def match_group_command(event: MessageEvent, state: T_State) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    text = event.get_plaintext()
    config = get_message_config()
    action = find_command_action(
        text,
        config.group_commands,
        is_allowed=lambda candidate: is_group_feature_allowed(
            event.user_id,
            event.group_id,
            candidate.feature,
        ),
    )
    if action is not None:
        state[GROUP_ACTION_KEY] = action
        return True

    return False


def is_group_push_subscription_manager(event: GroupMessageEvent) -> bool:
    return can_manage_group_event(event)


async def match_push_subscription_command(
    event: MessageEvent,
    _state: T_State,
) -> bool:
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False

    config = get_message_config().push_unsubscribe

    text = event.get_plaintext()
    if command_text_matches(text, PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS):
        return True
    if command_text_matches(text, config.commands):
        return True
    return command_text_matches(text, config.restore_commands)


async def match_push_time_command(
    event: MessageEvent,
    _state: T_State,
) -> bool:
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False
    if isinstance(event, GroupMessageEvent) and not is_group_push_subscription_manager(
        event
    ):
        return False
    return command_text_matches(event.get_plaintext(), PUSH_TIME_COMMANDS)


__all__ = [
    "GROUP_ACTION_KEY",
    "PRIVATE_ACTION_KEY",
    "is_group_push_subscription_manager",
    "match_group_command",
    "match_private_command",
    "match_push_subscription_command",
    "match_push_time_command",
]
