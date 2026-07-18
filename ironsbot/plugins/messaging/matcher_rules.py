from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.core.commands import command_text_matches
from ironsbot.shared.permissions import can_manage_group_event

from .push_management_runtime import (
    PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS,
    PUSH_TIME_COMMANDS,
)
from .runtime_service import find_command_action

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.config.models.message import (
        GroupCommandMessageAction,
        PrivateCommandMessageAction,
        PushUnsubscribeConfig,
    )
    from ironsbot.plugins.messaging.runtime_service import MessagingResources

PRIVATE_ACTION_KEY = "_message_action_private"
GROUP_ACTION_KEY = "_message_action_group"


def private_action_allowed(
    messaging: MessagingResources,
    event: PrivateMessageEvent,
    action: PrivateCommandMessageAction,
) -> bool:
    return messaging.features.is_private_feature_allowed(
        event.user_id,
        action.feature,
    )


async def match_private_command(
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingResources,
    actions: Sequence[PrivateCommandMessageAction],
) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    text = event.get_plaintext()
    action = find_command_action(
        text,
        actions,
        is_allowed=lambda candidate: private_action_allowed(
            messaging, event, candidate
        ),
    )
    if action is not None:
        state[PRIVATE_ACTION_KEY] = action
        return True

    return False


async def match_group_command(
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingResources,
    actions: Sequence[GroupCommandMessageAction],
) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    text = event.get_plaintext()
    action = find_command_action(
        text,
        actions,
        is_allowed=lambda candidate: messaging.features.is_group_feature_allowed(
            event.user_id,
            event.group_id,
            candidate.feature,
        ),
    )
    if action is not None:
        state[GROUP_ACTION_KEY] = action
        return True

    return False


def is_group_push_subscription_manager(
    messaging: MessagingResources,
    event: GroupMessageEvent,
) -> bool:
    return can_manage_group_event(messaging.features, event)


async def match_push_subscription_command(
    event: MessageEvent,
    state: T_State,
    *,
    config: PushUnsubscribeConfig,
) -> bool:
    del state
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False

    text = event.get_plaintext()
    if command_text_matches(text, PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS):
        return True
    if command_text_matches(text, config.commands):
        return True
    return command_text_matches(text, config.restore_commands)


async def match_push_time_command(
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingResources,
) -> bool:
    del state
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False
    if isinstance(event, GroupMessageEvent) and not is_group_push_subscription_manager(
        messaging, event
    ):
        return False
    return command_text_matches(event.get_plaintext(), PUSH_TIME_COMMANDS)
