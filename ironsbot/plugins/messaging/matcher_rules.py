from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.runtime.permissions import can_manage_group_event

if TYPE_CHECKING:
    from ironsbot.services.messaging.service import MessagingService

PRIVATE_ACTION_KEY = "_message_action_private"
GROUP_ACTION_KEY = "_message_action_group"


async def match_private_command(
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    action = messaging.match_private_action(
        event.get_plaintext(),
        event.user_id,
    )
    if action is not None:
        state[PRIVATE_ACTION_KEY] = action
        return True

    return False


async def match_group_command(
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    action = messaging.match_group_action(
        event.get_plaintext(),
        user_id=event.user_id,
        group_id=event.group_id,
    )
    if action is not None:
        state[GROUP_ACTION_KEY] = action
        return True

    return False


def is_group_push_subscription_manager(
    messaging: MessagingService,
    event: GroupMessageEvent,
) -> bool:
    return can_manage_group_event(messaging, event)


async def match_push_subscription_command(
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
) -> bool:
    del state
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False

    return messaging.matches_subscription_command(event.get_plaintext())


async def match_push_time_command(
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
