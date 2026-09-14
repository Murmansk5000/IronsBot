from __future__ import annotations

from typing import TYPE_CHECKING, cast

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves at runtime

from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.integrations.onebot.matchers import (
    CommandPolicy,
    MatcherFactory,
    bind,
    bind_async,
)
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.replies import (
    event_sender_at_user_ids,
    finish_matcher_message,
)
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.portable_messaging_commands import (
    build_portable_messaging_operations,
)

from .matcher_rules import (
    MESSAGE_ACTION_KEY,
    match_message_command,
    match_push_subscription_command,
    match_push_time_command,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.config.models.messaging import MessageReplyAction
    from ironsbot.config.onebot_references import OneBotReferenceResolver
    from ironsbot.services.messaging.push_time import PushTimeOption
    from ironsbot.services.messaging.service import MessagingService, ReplyInteraction
    from ironsbot.services.portable_query_sessions import PortableQuerySessions


def _message_subscription_priority(registry: MatcherFactory) -> int:
    return max(registry.priority("message_commands") - 1, 0)


async def handle_message_command(
    matcher: Matcher,
    event: PrivateMessageEvent | GroupMessageEvent,
    state: T_State,
    *,
    references: OneBotReferenceResolver,
) -> None:
    action = state[MESSAGE_ACTION_KEY]
    at_user_ids = (
        [
            *event_sender_at_user_ids(event),
            *references.resolve_users(
                action.at_user_ids,
                location=f"messaging.commands.{action.id}.at_user_ids",
            ),
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
    prefix: str,
):
    def resolve(_event: object, state: T_State) -> str:
        action = cast("MessageReplyAction", state[MESSAGE_ACTION_KEY])
        return f"{prefix}.{action.id}"

    return resolve


def install(  # noqa: PLR0913 - wiring receives both configured reply families
    registry: MatcherFactory,
    refresh_push_time_jobs: Callable[[PushTimeOption], Awaitable[None]],
    messaging: MessagingService,
    query_sessions: PortableQuerySessions,
    references: OneBotReferenceResolver,
    command_help_ids: tuple[str, ...],
    keyword_help_ids: tuple[str, ...],
) -> None:
    portable_operations = build_portable_messaging_operations(
        messaging,
        query_sessions,
        refresh_push_time_jobs=refresh_push_time_jobs,
    )
    routes: tuple[tuple[ReplyInteraction, str, tuple[str, ...]], ...] = (
        ("direct", "message", command_help_ids),
        ("automatic", "message.keyword", keyword_help_ids),
    )
    for interaction, prefix, help_ids in routes:
        if not help_ids:
            continue
        command_matcher = registry.on_message(
            policy=CommandPolicy.command(
                _action_command_id(prefix),
                help_ids=help_ids,
                closes_active_conversation=interaction == "direct",
            ),
            rule=Rule(
                bind(
                    match_message_command, messaging=messaging, interaction=interaction
                )
            )
            & explicit_command(),
            priority=registry.priority("message_commands"),
            block=True,
        )
        command_matcher.append_handler(
            bind_async(
                handle_message_command,
                references=references,
            )
        )

    subscription_matcher = registry.on_message(
        policy=CommandPolicy.command(
            "messaging.push_subscription", help_ids=("messaging.push_subscription",)
        ),
        rule=Rule(bind(match_push_subscription_command, messaging=messaging))
        & explicit_command(),
        priority=_message_subscription_priority(registry),
        block=True,
    )
    push_time_matcher = registry.on_message(
        policy=CommandPolicy.command(
            "messaging.push_time", help_ids=("messaging.push_time",)
        ),
        rule=(
            Rule(bind(match_push_time_command, messaging=messaging))
            & explicit_command()
        ),
        priority=_message_subscription_priority(registry),
        block=True,
    )
    subscription_matcher.append_handler(
        make_portable_query_handler(
            portable_operations["messaging.push_subscription"],
            query_sessions,
            ActionDefinition("messaging.push_subscription", "推送订阅管理"),
        )
    )
    push_time_matcher.append_handler(
        make_portable_query_handler(
            portable_operations["messaging.push_time"],
            query_sessions,
            ActionDefinition("messaging.push_time", "推送时间管理"),
        )
    )
