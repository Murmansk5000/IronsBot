from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (  # noqa: TC002 - NoneBot resolves at runtime
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves at runtime

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
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

if TYPE_CHECKING:
    from .push_time_handlers import RefreshPushTimeJobs


def _message_subscription_priority() -> int:
    return max(get_matcher_priority("message_commands", 4) - 1, 0)


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


def _action_command_id(
    state_key: str,
    prefix: str,
):
    def resolve(_event: object, state: T_State) -> str:
        action = state.get(state_key)
        action_id = str(getattr(action, "id", "")).strip()
        return f"{prefix}.{action_id}" if action_id else prefix

    return resolve


def install(
    registry: MatcherRegistry,
    refresh_push_time_jobs: RefreshPushTimeJobs,
) -> None:
    private_matcher = registry.on_message(
        policy=CommandPolicy.command(
            _action_command_id(PRIVATE_ACTION_KEY, "message_private")
        ),
        rule=Rule(match_private_command) & no_reply(),
        priority=get_matcher_priority("message_commands", 4),
        block=True,
    )
    private_matcher.append_handler(handle_private_command)

    subscription_matcher = registry.on_message(
        policy=CommandPolicy.exempt(
            "second-level subscription toggle conversation"
        ),
        rule=Rule(match_push_subscription_command) & no_reply(),
        priority=_message_subscription_priority(),
        block=True,
    )
    push_time_matcher = registry.on_message(
        policy=CommandPolicy.exempt("second-level push time conversation"),
        rule=Rule(match_push_time_command) & no_reply(),
        priority=_message_subscription_priority(),
        block=True,
    )
    register_push_management_handlers(
        push_subscription_matcher=subscription_matcher,
        push_time_matcher=push_time_matcher,
        refresh_push_time_jobs=refresh_push_time_jobs,
    )

    group_matcher = registry.on_message(
        policy=CommandPolicy.command(
            _action_command_id(GROUP_ACTION_KEY, "message_group")
        ),
        rule=Rule(match_group_command) & no_reply(),
        priority=get_matcher_priority("message_commands", 4),
        block=True,
    )
    group_matcher.append_handler(handle_group_command)


__all__ = ["handle_group_command", "handle_private_command", "install"]
