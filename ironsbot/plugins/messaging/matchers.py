from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import on_message
from nonebot.rule import Rule

from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.utils.rule import no_reply

from .command_handlers import (
    dispatch_group_command,
    dispatch_private_command,
    register_messaging_plugin,
)
from .matcher_rules import (
    match_group_command,
    match_private_command,
    match_push_subscription_command,
    match_push_time_command,
)
from .push_management_handlers import register_push_management_handlers
from .runtime import refresh_push_time_jobs

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
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


register_messaging_plugin(
    private_matcher=private_command_matcher,
    group_matcher=group_command_matcher,
)


@private_command_matcher.handle()
async def handle_private_command(
    event: PrivateMessageEvent,
    state: T_State,
) -> None:
    await dispatch_private_command(
        private_matcher=private_command_matcher,
        event=event,
        state=state,
    )


register_push_management_handlers(
    push_subscription_matcher=push_subscription_matcher,
    push_time_matcher=push_time_matcher,
    refresh_push_time_jobs=refresh_push_time_jobs,
)


@group_command_matcher.handle()
async def handle_group_command(event: GroupMessageEvent, state: T_State) -> None:
    await dispatch_group_command(
        group_matcher=group_command_matcher,
        event=event,
        state=state,
    )


__all__ = [
    "group_command_matcher",
    "handle_group_command",
    "handle_private_command",
    "private_command_matcher",
    "push_subscription_matcher",
    "push_time_matcher",
]
