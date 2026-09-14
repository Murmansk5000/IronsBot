# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves this at runtime

from ironsbot.core.outbound import (
    DeliveryFailureKind,
    OutboundMessage,
    SendResult,
)
from ironsbot.integrations.onebot.matchers import queued_conversation_is_cancelled
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_rendering import (
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.outbound_messenger import onebot_result_message_id
from ironsbot.services.portable_reply import (
    PortableOperation,
    as_portable_reply,
    deliver_reply_stages,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ReplyMessage = str | Message | MessageSegment


def render_text(text: str) -> str:
    return text.replace("\\n", "\n")


def build_message(
    text: ReplyMessage,
    at_user_ids: Iterable[int] = (),
) -> Message:
    message = Message()
    for user_id in dict.fromkeys(at_user_ids):
        message += MessageSegment.at(user_id)
        message += MessageSegment.text(" ")
    message += (
        text
        if isinstance(text, (Message, MessageSegment))
        else MessageSegment.text(render_text(text))
    )
    return message


def append_text_hint(message: str | Message, hint: str) -> str | Message:
    if isinstance(message, Message):
        if hint not in str(message):
            message += MessageSegment.text(f"\n\n{hint}")
        return message
    text = message.rstrip()
    return text if hint in text else hint if not text else f"{text}\n\n{hint}"


def prepend_text_hint(message: str | Message, hint: str) -> str | Message:
    if isinstance(message, Message):
        if hint not in str(message):
            message = MessageSegment.text(f"{hint}\n") + message
        return message
    text = message.lstrip()
    return text if hint in text else hint if not text else f"{hint}\n{text}"


def event_sender_at_user_ids(event: MessageEvent | None) -> tuple[int, ...]:
    if not isinstance(event, GroupMessageEvent):
        return ()
    if event.user_id == event.self_id:
        return ()

    return (event.user_id,)


async def send_matcher_message(
    matcher: Any,
    message: ReplyMessage,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    del event
    if queued_conversation_is_cancelled(matcher):
        return
    await matcher.send(build_message(message, at_user_ids=at_user_ids))


async def finish_matcher_message(
    matcher: Any,
    message: ReplyMessage,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    del event
    if queued_conversation_is_cancelled(matcher):
        raise FinishedException
    await matcher.finish(build_message(message, at_user_ids=at_user_ids))


async def send_event_reply(
    matcher: Any,
    event: MessageEvent,
    message: ReplyMessage,
) -> None:
    await send_matcher_message(
        matcher,
        message,
        at_user_ids=event_sender_at_user_ids(event),
        event=event,
    )


async def finish_event_reply(
    matcher: Any,
    event: MessageEvent,
    message: ReplyMessage,
) -> None:
    await finish_matcher_message(
        matcher,
        message,
        at_user_ids=event_sender_at_user_ids(event),
        event=event,
    )


async def send_portable_event_reply(
    matcher: Any,
    event: MessageEvent,
    message: OutboundMessage,
) -> SendResult:
    if queued_conversation_is_cancelled(matcher):
        return SendResult(
            delivered=False,
            error_code="conversation_cancelled",
            failure_kind=DeliveryFailureKind.PERMANENT,
        )
    rendered = render_onebot_outbound_message(
        message,
        conversation=message_input_context(event).message.conversation,
    )
    result = await matcher.send(
        build_message(
            rendered,
            at_user_ids=event_sender_at_user_ids(event),
        )
    )
    message_id = onebot_result_message_id(result)
    if message_id is None:
        return SendResult(
            delivered=False,
            error_code="missing_message_id",
            error_message="OneBot matcher send response omitted message_id",
            failure_kind=DeliveryFailureKind.UNCERTAIN,
        )
    return SendResult(delivered=True, message_id=message_id)


async def run_portable_operation(
    matcher: Matcher,
    event: MessageEvent,
    operation: PortableOperation,
) -> None:
    """Run one shared command operation from a OneBot matcher."""

    context = message_input_context(event)
    result = await operation(context.text.strip(), context)
    await deliver_reply_stages(
        lambda message: send_portable_event_reply(matcher, event, message),
        context.message,
        as_portable_reply(result),
    )


async def finish_message_sequence(
    matcher: Any,
    messages: Sequence[ReplyMessage],
    *,
    event: MessageEvent | None = None,
    interval_seconds: float = 0.5,
) -> None:
    if not messages:
        return

    at_user_ids = event_sender_at_user_ids(event)

    for message in messages[:-1]:
        await send_matcher_message(
            matcher,
            message,
            at_user_ids=at_user_ids,
            event=event,
        )
        await asyncio.sleep(interval_seconds)

    await finish_matcher_message(
        matcher,
        messages[-1],
        at_user_ids=at_user_ids,
        event=event,
    )
