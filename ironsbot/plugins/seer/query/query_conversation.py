# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot_plugin_saa import Image, MessageFactory

from ironsbot.runtime.matchers import queued_conversation_is_cancelled
from ironsbot.runtime.params import parse_string_arg
from ironsbot.runtime.prompts import Prompt, PromptItem, enter_prompt
from ironsbot.runtime.semantic_requests import (
    ActionDefinition,
    SemanticTarget,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.query_result import QueryResult

if TYPE_CHECKING:
    from ironsbot.services.seer.query_result import QueryReply

T = TypeVar("T")
SearchQuery = Callable[[str], Awaitable[QueryResult[T]]]
SelectionQuery = Callable[[T], Awaitable[QueryResult[Any]]]


def _raise_if_selection_cancelled(matcher: Matcher) -> None:
    if queued_conversation_is_cancelled(matcher):
        raise FinishedException


def build_reply(reply: QueryReply) -> MessageFactory:
    message = MessageFactory()
    if reply.leading_text:
        message += reply.leading_text
    if reply.image is not None:
        message += Image(reply.image)
    elif reply.image_error:
        message += reply.image_error
    if reply.text:
        message += reply.text
    return message


async def send_query_reply(
    reply: QueryReply,
    event: Event,
    *,
    finish: bool,
) -> None:
    """Send a query reply consistently for direct and menu selections."""
    message = build_reply(reply)
    kwargs = {"at_sender": isinstance(event, GroupMessageEvent)}
    if finish:
        await message.finish(**kwargs)
    else:
        await message.send(**kwargs)


def make_query_handler(
    search: SearchQuery[T],
    select: SelectionQuery[T],
    prompt_title: str,
    action: ActionDefinition,
) -> Callable[[Matcher, T_State, Event], Awaitable[None]]:
    async def resolve_selection(
        item: PromptItem[T],
        matcher: Matcher,
        event: Event,
    ) -> None:
        try:
            result = await select(item.value)
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
        try:
            result = await search(parse_string_arg(state))
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
