from __future__ import annotations

from typing import TYPE_CHECKING, cast

from nonebot.adapters.onebot.v11 import (  # noqa: TC002 - NoneBot resolves annotations
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves at runtime

from ironsbot.core.platform import ActorRef, Platform
from ironsbot.integrations.onebot.matcher_support import bind, bind_async
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import (
    make_portable_operation_handler,
    make_portable_query_handler,
)
from ironsbot.integrations.onebot.rules import explicit_command, member_targets_command
from ironsbot.services.messaging.topic_commands import (
    build_topic_operations,
    parse_topic_command,
    topic_command_contracts,
)
from ironsbot.services.portable_messaging_commands import (
    build_portable_mention_operation,
    build_portable_messaging_operations,
    build_portable_text_operation,
)

from .matcher_rules import (
    MESSAGE_ACTION_KEY,
    match_mention_reply,
    match_message_command,
    match_push_subscription_command,
    match_push_time_command,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.config.models.messaging import (
        MessageReplyAction,
    )
    from ironsbot.config.qq_references import QQReferenceResolver
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.messaging.push_time import PushTimeOption
    from ironsbot.services.messaging.service import MessagingService, ReplyInteraction
    from ironsbot.services.portable_query_sessions import PortableQuerySessions

    RefreshPushTimeJobs = Callable[[PushTimeOption], Awaitable[None]]


def _message_subscription_priority(registry: MatcherFactory) -> int:
    return max(registry.priority("message_commands") - 1, 0)


async def handle_message_command(
    matcher: Matcher,
    event: PrivateMessageEvent | GroupMessageEvent,
    state: T_State,
    *,
    references: QQReferenceResolver,
    sessions: PortableQuerySessions,
) -> None:
    action = state[MESSAGE_ACTION_KEY]
    operation = build_portable_text_operation(
        action,
        tuple(
            ActorRef(Platform.ONEBOT, str(user_id))
            for user_id in references.resolve_users(
                action.at_user_ids,
                location=f"messaging.commands.{action.id}.at_user_ids",
            )
        ),
        None,
    )
    await make_portable_query_handler(operation, sessions)(matcher, state, event)


def _action_command_id(
    prefix: str,
):
    def resolve(_event: object, state: T_State) -> str:
        action = cast("MessageReplyAction", state[MESSAGE_ACTION_KEY])
        return f"{prefix}.{action.id}"

    return resolve


def install(  # noqa: PLR0913 - wiring receives both configured reply families
    registry: MatcherFactory,
    refresh_push_time_jobs: RefreshPushTimeJobs,
    messaging: MessagingService,
    references: QQReferenceResolver,
    command_help_ids: tuple[str, ...],
    keyword_help_ids: tuple[str, ...],
    query_sessions: PortableQuerySessions,
) -> None:
    if messaging.topics is not None:
        _install_topics(registry, messaging)

    routes: tuple[tuple[ReplyInteraction, str, tuple[str, ...]], ...] = (
        ("direct", "message", command_help_ids),
        ("automatic", "message.keyword", keyword_help_ids),
    )
    for interaction, prefix, help_ids in routes:
        if not help_ids:
            continue
        input_rule = (
            member_targets_command() if interaction == "direct" else explicit_command()
        )
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
            & input_rule,
            priority=registry.priority("message_commands"),
            block=True,
        )
        command_matcher.append_handler(
            bind_async(
                handle_message_command,
                references=references,
                sessions=query_sessions,
            )
        )

    if messaging.has_enabled_mention_replies:
        mention_matcher = registry.on_message(
            policy=CommandPolicy.exempt("configured mention reply"),
            rule=Rule(bind(match_mention_reply, messaging=messaging)),
            priority=registry.priority("mention_reply"),
            block=True,
        )
        mention_matcher.append_handler(
            make_portable_operation_handler(build_portable_mention_operation(messaging))
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
    operations = build_portable_messaging_operations(
        messaging, query_sessions, refresh_push_time_jobs=refresh_push_time_jobs
    )
    for matcher, command in (
        (subscription_matcher, "messaging.push_subscription"),
        (push_time_matcher, "messaging.push_time"),
    ):
        matcher.append_handler(
            make_portable_query_handler(operations[command], query_sessions)
        )


def _install_topics(registry: MatcherFactory, messaging: MessagingService) -> None:
    assert messaging.topics is not None
    topics = messaging.topics
    operations = build_topic_operations(topics)

    def matches(event: PrivateMessageEvent | GroupMessageEvent) -> bool:
        return (
            parse_topic_command(message_input_context(event).text, topics.known_keys)
            is not None
        )

    def command_id(event: MessageEvent, _state: T_State) -> str:
        parsed = parse_topic_command(
            message_input_context(event).text, topics.known_keys
        )
        assert parsed is not None
        return f"messaging.topic.{parsed.action}"

    async def operation(text: str, context: MessageInputContext):
        parsed = parse_topic_command(text, topics.known_keys)
        if parsed is None:
            return None
        return await operations[f"messaging.topic.{parsed.action}"](text, context)

    matcher = registry.on_message(
        policy=CommandPolicy.command(
            command_id,
            help_ids=tuple(contract.id for contract in topic_command_contracts()),
        ),
        rule=Rule(matches) & explicit_command(),
        priority=_message_subscription_priority(registry),
        block=True,
    )
    matcher.append_handler(make_portable_operation_handler(operation))
