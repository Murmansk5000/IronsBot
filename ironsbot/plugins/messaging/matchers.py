from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves at runtime

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry, bind, bind_async
from ironsbot.runtime.replies import (
    event_sender_at_user_ids,
    finish_matcher_message,
)
from ironsbot.runtime.rules import explicit_command

from .matcher_rules import (
    MESSAGE_ACTION_KEY,
    match_message_command,
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


async def handle_message_command(
    matcher: Matcher,
    event: PrivateMessageEvent | GroupMessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
) -> None:
    action = state[MESSAGE_ACTION_KEY]
    at_user_ids = (
        [
            *event_sender_at_user_ids(event),
            *messaging._features.resolve_user_refs(action.at_user_ids),
        ]
        if isinstance(event, GroupMessageEvent)
        else []
    )
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
    command_help_ids: tuple[str, ...],
) -> None:
    if command_help_ids:
        command_matcher = registry.on_message(
            policy=CommandPolicy.command(
                _action_command_id(MESSAGE_ACTION_KEY, "message"),
                help_ids=command_help_ids,
            ),
            rule=Rule(bind(match_message_command, messaging=messaging))
            & explicit_command(),
            priority=registry.priority("message_commands"),
            block=True,
        )
        command_matcher.append_handler(
            bind_async(handle_message_command, messaging=messaging)
        )

    subscription_matcher = registry.on_message(
        policy=CommandPolicy.exempt(
            "second-level subscription toggle conversation"
        ),
        rule=Rule(bind(match_push_subscription_command, messaging=messaging))
        & explicit_command(),
        priority=_message_subscription_priority(registry),
        block=True,
    )
    push_time_matcher = registry.on_message(
        policy=CommandPolicy.exempt("second-level push time conversation"),
        rule=(
            Rule(bind(match_push_time_command, messaging=messaging))
            & explicit_command()
        ),
        priority=_message_subscription_priority(registry),
        block=True,
    )
    subscription_matcher.handle()(
        bind_async(
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
