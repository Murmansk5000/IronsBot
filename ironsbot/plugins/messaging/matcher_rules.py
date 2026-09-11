from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.config.models.messaging import (
    MessageCommandAction,
    MessageKeywordReplyAction,
)
from ironsbot.runtime.message_input import is_self_command, message_input_context
from ironsbot.runtime.permissions import can_manage_group_event

if TYPE_CHECKING:
    from ironsbot.services.messaging.service import MessagingService

MESSAGE_ACTION_KEY = "_message_action"
MESSAGE_TARGET_IDS_KEY = "_message_target_ids"


def match_message_command(
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
) -> bool:
    if isinstance(event, PrivateMessageEvent):
        action = messaging.match_private_action(
            event.get_plaintext(),
            event.user_id,
        )
    elif isinstance(event, GroupMessageEvent):
        action = messaging.match_group_action(
            event.get_plaintext(),
            user_id=event.user_id,
            group_id=event.group_id,
        )
    else:
        return False

    if action is not None:
        if is_self_command(event) and isinstance(action, MessageKeywordReplyAction):
            return False
        context = message_input_context(event)
        if context.has_member_mentions:
            if (
                not isinstance(action, MessageCommandAction)
                or not context.member_user_ids
            ):
                return False
            state[MESSAGE_TARGET_IDS_KEY] = context.member_user_ids
        state[MESSAGE_ACTION_KEY] = action
        return True

    return False


def match_group_mention_reply(
    event: GroupMessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
) -> bool:
    action = messaging.match_group_mention_reply(
        user_id=event.user_id,
        group_id=event.group_id,
    )
    if action is None:
        return False
    state[MESSAGE_ACTION_KEY] = action
    return True


def is_group_push_subscription_manager(
    messaging: MessagingService,
    event: GroupMessageEvent,
) -> bool:
    return can_manage_group_event(messaging, event)


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
