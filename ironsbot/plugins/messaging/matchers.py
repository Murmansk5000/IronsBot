from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import on_message
from nonebot.rule import Rule

from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    event_sender_at_user_ids,
    finish_matcher_message,
)
from ironsbot.utils.rule import no_reply

from .matcher_rules import (
    GROUP_ACTION_KEY,
    PRIVATE_ACTION_KEY,
    match_group_command,
    match_private_command,
    match_push_subscription_command,
    match_push_time_command,
)
from .push_management_handlers import register_push_management_handlers
from .runtime import refresh_push_time_jobs

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State


def _message_subscription_priority() -> int:
    return max(get_matcher_priority("message_commands", 4) - 1, 0)


private_command_matcher = on_message(
    rule=Rule(match_private_command) & no_reply(),
    priority=get_matcher_priority("message_commands", 4),
    block=True,
)

push_subscription_matcher = on_message(
    rule=Rule(match_push_subscription_command) & no_reply(),
    priority=_message_subscription_priority(),
    block=True,
)

push_time_matcher = on_message(
    rule=Rule(match_push_time_command) & no_reply(),
    priority=_message_subscription_priority(),
    block=True,
)

group_command_matcher = on_message(
    rule=Rule(match_group_command) & no_reply(),
    priority=get_matcher_priority("message_commands", 4),
    block=True,
)


@private_command_matcher.handle()
async def handle_private_command(
    matcher: Matcher,
    event: PrivateMessageEvent,
    state: T_State,
) -> None:
    action = state[PRIVATE_ACTION_KEY]
    await finish_matcher_message(
        matcher,
        action.message,
        event=event,
    )


register_push_management_handlers(
    push_subscription_matcher=push_subscription_matcher,
    push_time_matcher=push_time_matcher,
    refresh_push_time_jobs=refresh_push_time_jobs,
)


@group_command_matcher.handle()
async def handle_group_command(
    matcher: Matcher,
    event: GroupMessageEvent,
    state: T_State,
) -> None:
    action = state[GROUP_ACTION_KEY]
    at_user_ids = [
        *event_sender_at_user_ids(event),
        *action.at_user_ids,
    ]
    await finish_matcher_message(
        matcher,
        action.message,
        at_user_ids=at_user_ids,
        event=event,
    )


__all__ = [
    "group_command_matcher",
    "handle_group_command",
    "handle_private_command",
    "private_command_matcher",
    "push_subscription_matcher",
    "push_time_matcher",
]
