# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticTarget,
)
from ironsbot.integrations.onebot.matchers import queued_conversation_is_cancelled
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.params import parse_string_arg
from ironsbot.services.seer.query_result import QueryResult

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.seer.query_result import QueryReply

T = TypeVar("T")
SearchQuery = Callable[..., Awaitable[QueryResult[T]]]
SelectionQuery = Callable[..., Awaitable[QueryResult[Any]]]
_QUERY_SELECTION_NAMESPACE = "selection_prompt"


def _raise_if_selection_cancelled(matcher: Matcher) -> None:
    if queued_conversation_is_cancelled(matcher):
        raise FinishedException


async def send_query_reply(
    reply: QueryReply,
    event: Event,
    *,
    finish: bool,
) -> None:
    """Send direct and selected query results with consistent group mentions."""

    message = render_onebot_outbound_message(reply.to_outbound())
    kwargs = {"at_sender": isinstance(event, GroupMessageEvent)}
    if finish:
        await Matcher.finish(message, **kwargs)
    else:
        await Matcher.send(message, **kwargs)


def make_query_handler(  # noqa: PLR0913 - query adapter compatibility
    search: SearchQuery[T],
    select: SelectionQuery,
    prompt_title: str,
    action: ActionDefinition,
    *,
    sessions: PortableQuerySessions | None = None,
    with_execution_identity: bool = False,
) -> Callable[[Matcher, T_State, Event], Awaitable[None]]:
    from ironsbot.integrations.onebot.portable_queries import (
        make_portable_query_handler,
        release_query_menu_admission,
    )
    from ironsbot.services.portable_query_sessions import (
        PortableQuerySessions,
        QueryOperationSpec,
    )

    shared_sessions = sessions or PortableQuerySessions()

    async def handle(matcher: Matcher, state: T_State, event: Event) -> None:
        argument = parse_string_arg(state)

        async def search_contextual(
            value: str, context: MessageInputContext
        ) -> QueryResult[T]:
            return (
                await search(value, execution_identity=context.execution_identity)
                if with_execution_identity
                else await search(value)
            )

        async def select_contextual(
            value: T, context: MessageInputContext
        ) -> QueryResult[Any]:
            return (
                await select(value, execution_identity=context.execution_identity)
                if with_execution_identity
                else await select(value)
            )

        async def operation(
            text: str, context: MessageInputContext
        ) -> OutboundMessage | None:
            del text
            message = await shared_sessions.begin(
                context,
                argument=argument,
                spec=QueryOperationSpec(
                    parser=lambda _text: argument,
                    search=search,
                    select=select,
                    contextual_search=search_contextual,
                    contextual_select=select_contextual,
                    prompt_title=prompt_title,
                    action=action,
                ),
            )
            if message is not None and message.prompt is not None:
                release_query_menu_admission(matcher, shared_sessions)
            return message

        await make_portable_query_handler(operation, shared_sessions)(
            matcher, state, event
        )

    return handle


def _is_digit_selection_input(event: MessageEvent) -> bool:
    return event.get_plaintext().strip().isdigit()


def _query_choice_semantic_target(choice: object) -> SemanticTarget:
    explicit = getattr(choice, "semantic_target", None)
    if isinstance(explicit, SemanticTarget):
        return explicit
    value = getattr(choice, "value", None)
    if isinstance(value, (str, int)):
        return SemanticTarget(key=str(value), display=str(value))
    for attribute in ("id", "item_id", "pet_id", "resource_id"):
        candidate = getattr(value, attribute, None)
        if isinstance(candidate, (str, int)):
            return SemanticTarget(key=str(candidate), display=str(candidate))
    name = str(getattr(choice, "name", "")).strip()
    description = str(getattr(choice, "description", "")).strip()
    return SemanticTarget(
        key=f"{name}\x1f{description}",
        display=name or description,
    )
