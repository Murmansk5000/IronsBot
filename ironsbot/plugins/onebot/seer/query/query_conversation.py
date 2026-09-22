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
from ironsbot.integrations.onebot.conversations import (
    begin_event_reply_conversation,
)
from ironsbot.integrations.onebot.matchers import queued_conversation_is_cancelled
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.params import parse_string_arg
from ironsbot.integrations.onebot.prompts import Prompt, PromptItem, enter_prompt
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.query_result import QueryResult

if TYPE_CHECKING:
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


def make_query_handler(  # noqa: C901
    search: SearchQuery[T],
    select: SelectionQuery,
    prompt_title: str,
    action: ActionDefinition,
    *,
    with_execution_identity: bool = False,
) -> Callable[[Matcher, T_State, Event], Awaitable[None]]:
    async def resolve_selection(
        item: PromptItem[T],
        matcher: Matcher,
        event: Event,
    ) -> None:
        try:
            result = (
                await select(
                    item.value,
                    execution_identity=message_input_context(event).execution_identity,
                )
                if with_execution_identity
                else await select(item.value)
            )
        except DataUnavailableError:
            _raise_if_selection_cancelled(matcher)
            await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
            return
        _raise_if_selection_cancelled(matcher)
        if result.message:
            await matcher.finish(result.message)
            return
        if result.reply is not None:
            await send_query_reply(result.reply, event, finish=False)

    async def handle(
        matcher: Matcher,
        state: T_State,
        event: Event,
    ) -> None:
        if isinstance(event, MessageEvent):
            await begin_event_reply_conversation(
                matcher,
                event,
                namespace=_QUERY_SELECTION_NAMESPACE,
                handlers=[resolve_selection],
                pending_reply_check=_is_digit_selection_input,
                reply_check=_is_digit_selection_input,
            )
        try:
            result = (
                await search(
                    parse_string_arg(state),
                    execution_identity=message_input_context(event).execution_identity,
                )
                if with_execution_identity
                else await search(parse_string_arg(state))
            )
        except DataUnavailableError:
            await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
            return
        if result.message:
            await matcher.finish(result.message)
        if result.reply is not None:
            await send_query_reply(result.reply, event, finish=True)
        if not result.choices:
            raise FinishedException
        await enter_prompt(
            matcher,
            event,
            state,
            Prompt(
                title=prompt_title,
                action=action,
                items=[
                    PromptItem(
                        choice.name,
                        choice.description,
                        choice.value,
                        is_sub_prompt=choice.is_sub_choice,
                        semantic_target=_query_choice_semantic_target(choice),
                    )
                    for choice in result.choices
                ],
            ),
            resolve_selection,
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
