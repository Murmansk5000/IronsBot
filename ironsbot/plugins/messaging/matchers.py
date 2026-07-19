from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (  # noqa: TC002 - NoneBot resolves at runtime
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves at runtime

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.replies import (
    event_sender_at_user_ids,
    finish_matcher_message,
)
from ironsbot.runtime.rules import no_reply

from .matcher_rules import (
    GROUP_ACTION_KEY,
    PRIVATE_ACTION_KEY,
    match_group_command,
    match_private_command,
    match_push_subscription_command,
    match_push_time_command,
)
from .push_subscription_handlers import handle_push_subscription_menu
from .push_time_handlers import build_push_time_menu_handler

if TYPE_CHECKING:
    from ironsbot.services.messaging.service import MessagingService

    from .push_time_handlers import RefreshPushTimeJobs


def _message_subscription_priority(registry: MatcherRegistry) -> int:
    return max(registry.priority("message_commands") - 1, 0)


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
    messaging: MessagingService,
) -> None:
    private_matcher = registry.on_message(
        policy=CommandPolicy.command(
            _action_command_id(PRIVATE_ACTION_KEY, "message_private")
        ),
        rule=Rule(
            partial(
                match_private_command,
                messaging=messaging,
            )
        )
        & no_reply(),
        priority=registry.priority("message_commands"),
        block=True,
    )
    private_matcher.append_handler(handle_private_command)

    subscription_matcher = registry.on_message(
        policy=CommandPolicy.exempt(
            "second-level subscription toggle conversation"
        ),
        rule=Rule(
            partial(
                match_push_subscription_command,
                messaging=messaging,
            )
        )
        & no_reply(),
        priority=_message_subscription_priority(registry),
        block=True,
    )
    push_time_matcher = registry.on_message(
        policy=CommandPolicy.exempt("second-level push time conversation"),
        rule=Rule(partial(match_push_time_command, messaging=messaging)) & no_reply(),
        priority=_message_subscription_priority(registry),
        block=True,
    )
    subscription_matcher.handle()(
        partial(
            handle_push_subscription_menu,
            messaging=messaging,
        )
    )
    push_time_matcher.handle()(
        build_push_time_menu_handler(
            refresh_push_time_jobs,
            messaging,
        )
    )

    group_matcher = registry.on_message(
        policy=CommandPolicy.command(
            _action_command_id(GROUP_ACTION_KEY, "message_group")
        ),
        rule=Rule(
            partial(
                match_group_command,
                messaging=messaging,
            )
        )
        & no_reply(),
        priority=registry.priority("message_commands"),
        block=True,
    )
    group_matcher.append_handler(handle_group_command)
