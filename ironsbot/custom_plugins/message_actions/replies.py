import asyncio
from collections.abc import Iterable

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.matcher import Matcher

from ironsbot.custom_plugins.superuser_priority import wait_for_superuser_priority

from .reply_limits import limit_message_by_reply_lines
from .text import build_message


def event_sender_at_user_ids(
    event: MessageEvent | None,
    *,
    mention_sender: bool = False,
) -> tuple[int, ...]:
    del mention_sender

    if not isinstance(event, GroupMessageEvent):
        return ()

    return (event.user_id,)


async def send_matcher_message(
    matcher: Matcher,
    message: str | Message,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    await wait_for_superuser_priority(event)
    message = limit_message_by_reply_lines(message, event=event)
    await matcher.send(build_message(message, at_user_ids=at_user_ids))


async def finish_matcher_message(
    matcher: Matcher,
    message: str | Message,
    *,
    at_user_ids: Iterable[int] = (),
    event: MessageEvent | None = None,
) -> None:
    await wait_for_superuser_priority(event)
    message = limit_message_by_reply_lines(message, event=event)
    await matcher.finish(build_message(message, at_user_ids=at_user_ids))


async def send_event_reply(
    matcher: Matcher,
    event: MessageEvent,
    message: str | Message,
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
    message: str | Message,
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
    messages: list[str | Message],
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
