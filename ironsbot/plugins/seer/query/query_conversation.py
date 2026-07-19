# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot_plugin_saa import Image, MessageFactory

from ironsbot.runtime.params import parse_string_arg
from ironsbot.runtime.prompts import Prompt, PromptItem, enter_prompt
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.query_result import QueryResult

if TYPE_CHECKING:
    from ironsbot.services.seer.query_result import QueryReply

T = TypeVar("T")
SearchQuery = Callable[[str], Awaitable[QueryResult[T]]]
SelectionQuery = Callable[[T], Awaitable[QueryResult[Any]]]


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


def make_query_handler(
    search: SearchQuery[T],
    select: SelectionQuery[T],
    prompt_title: str,
) -> Callable[[Matcher, T_State, Event], Awaitable[None]]:
    async def resolve_selection(
        item: PromptItem[T],
        matcher: Matcher,
    ) -> None:
        try:
            result = await select(item.value)
        except DataUnavailableError:
            await matcher.finish(DATABASE_UNAVAILABLE_MESSAGE)
            return
        if result.message:
            await matcher.finish(result.message)
            return
        if result.reply is not None:
            await build_reply(result.reply).send()

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
            await build_reply(result.reply).finish()
        if not result.choices:
            raise FinishedException
        await enter_prompt(
            matcher,
            event,
            state,
            Prompt(
                title=prompt_title,
                items=[
                    PromptItem(
                        choice.name,
                        choice.description,
                        choice.value,
                        is_sub_prompt=choice.is_sub_choice,
                    )
                    for choice in result.choices
                ],
            ),
            resolve_selection,
        )

    return handle
