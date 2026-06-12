# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.matcher import Matcher

from .text import build_message

ReplyMessage = str | Message | MessageSegment
BeforeReplySendHook = Callable[[MessageEvent | None], Awaitable[None]]
ReplyMessageLimiter = Callable[
    [ReplyMessage, MessageEvent | None, int | None],
    ReplyMessage,
]


async def _noop_before_reply_send(_event: MessageEvent | None) -> None:
    return


def _identity_reply_message_limiter(
    message: ReplyMessage,
    _event: MessageEvent | None,
    _group_id: int | None,
) -> ReplyMessage:
    return message


_before_reply_send_hook: BeforeReplySendHook = _noop_before_reply_send
_reply_message_limiter: ReplyMessageLimiter = _identity_reply_message_limiter


def configure_reply_delivery_policy(
    *,
    before_send: BeforeReplySendHook | None = None,
    message_limiter: ReplyMessageLimiter | None = None,
) -> None:
    global _before_reply_send_hook, _reply_message_limiter

    if before_send is not None:
        _before_reply_send_hook = before_send
    if message_limiter is not None:
        _reply_message_limiter = message_limiter


def event_sender_at_user_ids(
    event: MessageEvent | None,
    *,
    mention_sender: bool = False,
) -> tuple[int, ...]:
    del mention_sender

    if not isinstance(event, GroupMessageEvent):
        return ()

    return (event.user_id,)


async def apply_reply_before_send(event: MessageEvent | None) -> None:
    await _before_reply_send_hook(event)


def limit_reply_message(
    message: ReplyMessage,
    *,
    event: MessageEvent | None = None,
    group_id: int | None = None,
) -> ReplyMessage:
    return _reply_message_limiter(message, event, group_id)


async def send_matcher_message(
    matcher: Matcher,
    message: ReplyMessage,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    await apply_reply_before_send(event)
    message = limit_reply_message(message, event=event)
    await matcher.send(build_message(message, at_user_ids=at_user_ids))


async def finish_matcher_message(
    matcher: Matcher,
    message: ReplyMessage,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    await apply_reply_before_send(event)
    message = limit_reply_message(message, event=event)
    await matcher.finish(build_message(message, at_user_ids=at_user_ids))


async def send_event_reply(
    matcher: Matcher,
    event: MessageEvent,
    message: ReplyMessage,
    *,
    mention_sender: bool = False,
) -> None:
    await send_matcher_message(
        matcher,
        message,
        at_user_ids=event_sender_at_user_ids(
            event,
            mention_sender=mention_sender,
        ),
        event=event,
    )


async def finish_event_reply(
    matcher: Matcher,
    event: MessageEvent,
    message: ReplyMessage,
    *,
    mention_sender: bool = False,
) -> None:
    await finish_matcher_message(
        matcher,
        message,
        at_user_ids=event_sender_at_user_ids(
            event,
            mention_sender=mention_sender,
        ),
        event=event,
    )


async def finish_message_sequence(
    matcher: Matcher,
    messages: list[ReplyMessage],
    *,
    event: MessageEvent | None = None,
    mention_sender: bool = False,
    interval_seconds: float = 0.5,
) -> None:
    if not messages:
        return

    at_user_ids = event_sender_at_user_ids(
        event,
        mention_sender=mention_sender,
    )

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
