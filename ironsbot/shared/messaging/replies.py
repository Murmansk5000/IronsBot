# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)

from .text import build_message

ReplyMessage = str | Message | MessageSegment
BeforeReplySendHook = Callable[[MessageEvent | None], Awaitable[None]]
async def _noop_before_reply_send(_event: MessageEvent | None) -> None:
    return


_before_reply_send_hook: BeforeReplySendHook = _noop_before_reply_send


def configure_reply_delivery_policy(
    *,
    before_send: BeforeReplySendHook | None = None,
) -> None:
    global _before_reply_send_hook  # noqa: PLW0603

    if before_send is not None:
        _before_reply_send_hook = before_send


def event_sender_at_user_ids(
    event: MessageEvent | None,
    *,
    mention_sender: bool = False,
) -> tuple[int, ...]:
    del mention_sender

    if not isinstance(event, GroupMessageEvent):
        return ()
    if event.user_id == event.self_id:
        return ()

    return (event.user_id,)


async def apply_reply_before_send(event: MessageEvent | None) -> None:
    await _before_reply_send_hook(event)


async def send_matcher_message(
    matcher: Any,
    message: ReplyMessage,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    await apply_reply_before_send(event)
    await matcher.send(build_message(message, at_user_ids=at_user_ids))


async def finish_matcher_message(
    matcher: Any,
    message: ReplyMessage,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    await apply_reply_before_send(event)
    await matcher.finish(build_message(message, at_user_ids=at_user_ids))


async def send_event_reply(
    matcher: Any,
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
    matcher: Any,
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
    matcher: Any,
    messages: Sequence[ReplyMessage],
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
