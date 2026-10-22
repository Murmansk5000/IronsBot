# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)

from ironsbot.core.outbound import (
    COMMAND_REPLY_TEMPLATE,
    OutboundMessage,
    ReplyTemplate,
    SendResult,
)
from ironsbot.integrations.onebot.errors import OneBotActionError
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_rendering import (
    parse_reply_message_id,
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.receipts import (
    onebot_send_failure,
    onebot_send_result,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ReplyMessage = str | Message | MessageSegment


def _event_reply_template(event: MessageEvent) -> ReplyTemplate:
    if event.user_id == event.self_id:
        return replace(COMMAND_REPLY_TEMPLATE, mention_sender=False)
    return COMMAND_REPLY_TEMPLATE


def render_text(text: str) -> str:
    return text.replace("\\n", "\n")


def build_message(
    text: ReplyMessage,
    at_user_ids: Iterable[int] = (),
    *,
    mention_separator: str = " ",
) -> Message:
    message = Message()
    for user_id in dict.fromkeys(at_user_ids):
        message += MessageSegment.at(user_id)
        message += MessageSegment.text(mention_separator)
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
    rendered = build_message(
        message,
        at_user_ids=at_user_ids,
        mention_separator=(
            COMMAND_REPLY_TEMPLATE.mention_separator if event is not None else " "
        ),
    )
    await matcher.send(
        build_event_reply_message(event, rendered) if event is not None else rendered
    )


async def finish_matcher_message(
    matcher: Any,
    message: ReplyMessage,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    rendered = build_message(
        message,
        at_user_ids=at_user_ids,
        mention_separator=(
            COMMAND_REPLY_TEMPLATE.mention_separator if event is not None else " "
        ),
    )
    await matcher.finish(
        build_event_reply_message(event, rendered) if event is not None else rendered
    )


async def send_event_reply(
    matcher: Any,
    event: MessageEvent,
    message: ReplyMessage,
) -> None:
    await send_matcher_message(matcher, message, event=event)


async def finish_event_reply(
    matcher: Any,
    event: MessageEvent,
    message: ReplyMessage,
) -> None:
    await finish_matcher_message(matcher, message, event=event)


async def send_portable_event_reply(
    matcher: Any,
    event: MessageEvent,
    message: OutboundMessage,
) -> SendResult:
    incoming = message_input_context(event).message
    prepared = _event_reply_template(event).prepare(incoming, message)
    rendered = render_onebot_outbound_message(
        prepared.message,
        conversation=incoming.conversation,
        reply_to_id=(
            prepared.context.message_id if prepared.context is not None else None
        ),
    )
    try:
        result = await matcher.send(
            Message(MessageSegment(**segment) for segment in rendered)
        )
    except OneBotActionError as error:
        return onebot_send_failure(error).result
    return onebot_send_result(result)


def build_event_reply_message(event: MessageEvent, message: ReplyMessage) -> Message:
    """Render legacy OneBot command output with the shared reply policy."""

    incoming = message_input_context(event).message
    native_message = Message(
        MessageSegment.text(render_text(message))
        if isinstance(message, str)
        else message
    )
    has_image = any(segment.type == "image" for segment in native_message)
    if has_image:
        native_message = _image_reply_without_sender(native_message, event.user_id)
    presentation = _event_reply_template(event).presentation(
        incoming,
        has_text=isinstance(message, str)
        or any(
            segment.type == "text" and bool(str(segment.data.get("text", "")))
            for segment in native_message
        ),
        has_mention=any(segment.type == "at" for segment in native_message),
        has_image=has_image,
    )
    rendered = Message()
    if presentation.context is not None and not any(
        segment.type == "reply" for segment in native_message
    ):
        rendered += MessageSegment.reply(
            parse_reply_message_id(presentation.context.message_id)
        )
    if presentation.mention_actor is not None:
        rendered += MessageSegment.at(int(presentation.mention_actor.id))
        rendered += MessageSegment.text(presentation.mention_separator)
    rendered += native_message
    return rendered


def _image_reply_without_sender(message: Message, user_id: int) -> Message:
    rendered = Message()
    removed_mention = False
    for segment in message:
        if segment.type == "at" and str(segment.data.get("qq")) == str(user_id):
            removed_mention = True
            continue
        if (
            removed_mention
            and segment.type == "text"
            and not str(segment.data.get("text", "")).strip()
        ):
            continue
        removed_mention = False
        rendered += segment
    return rendered


async def finish_message_sequence(
    matcher: Any,
    messages: Sequence[ReplyMessage],
    *,
    event: MessageEvent | None = None,
    interval_seconds: float = 0.5,
) -> None:
    if not messages:
        return

    for message in messages[:-1]:
        await send_matcher_message(
            matcher,
            message,
            event=event,
        )
        await asyncio.sleep(interval_seconds)

    await finish_matcher_message(
        matcher,
        messages[-1],
        event=event,
    )
