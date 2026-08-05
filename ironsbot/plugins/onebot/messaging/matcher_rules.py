from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.permissions import can_manage_group_event

if TYPE_CHECKING:
    from ironsbot.services.messaging.service import MessagingService

MESSAGE_ACTION_KEY = "_message_action"


def match_message_command(
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
) -> bool:
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False
    message = message_input_context(event).message
    action = messaging.match_action(
        message.text,
        actor=message.actor,
        conversation=message.conversation,
    )

    if action is not None:
        state[MESSAGE_ACTION_KEY] = action
        return True

    return False


def is_group_push_subscription_manager(
    messaging: MessagingService,
    event: GroupMessageEvent,
) -> bool:
    return can_manage_group_event(messaging.feature_policy, event)


def match_push_subscription_command(
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
) -> bool:
    del state
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False

    return messaging.matches_subscription_command(event.get_plaintext())


def match_push_time_command(
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
) -> bool:
    del state
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False
    if isinstance(event, GroupMessageEvent) and not is_group_push_subscription_manager(
        messaging, event
    ):
        return False
    return messaging.matches_push_time_command(event.get_plaintext())
