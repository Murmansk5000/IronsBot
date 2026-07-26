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

from ironsbot.core.messaging import (
    FIRE_MANUAL_LINK_MESSAGE,
    FIRE_MANUAL_URL,
    MessageTarget,
)
from ironsbot.runtime.matchers import get_reply_before_send

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ReplyMessage = str | Message | MessageSegment


def message_event_target(event: MessageEvent) -> MessageTarget:
    if isinstance(event, GroupMessageEvent):
        return MessageTarget("group", int(event.group_id))
    return MessageTarget("private", int(event.user_id))


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


def append_fire_manual_ad_message(message: Message) -> Message:
    if FIRE_MANUAL_URL not in str(message):
        message += MessageSegment.text(f"\n\n{FIRE_MANUAL_LINK_MESSAGE}")
    return message


def event_sender_at_user_ids(event: MessageEvent | None) -> tuple[int, ...]:
    if not isinstance(event, GroupMessageEvent):
        return ()
    if event.user_id == event.self_id:
        return ()

    return (event.user_id,)


async def apply_reply_before_send(
    matcher: Any,
    event: MessageEvent | None,
) -> None:
    hook = get_reply_before_send(matcher)
    if hook is not None:
        await hook(event)


async def send_matcher_message(
    matcher: Any,
    message: ReplyMessage,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    await apply_reply_before_send(matcher, event)
    await matcher.send(build_message(message, at_user_ids=at_user_ids))


async def finish_matcher_message(
    matcher: Any,
    message: ReplyMessage,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    await apply_reply_before_send(matcher, event)
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
