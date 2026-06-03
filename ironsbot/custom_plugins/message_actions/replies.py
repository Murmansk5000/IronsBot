import asyncio
from collections.abc import Iterable

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.matcher import Matcher

from .config import plugin_config
from .text import build_message


def event_sender_at_user_ids(
    event: MessageEvent | None,
    *,
    mention_sender: bool = False,
) -> tuple[int, ...]:
    if not isinstance(event, GroupMessageEvent):
        return ()

    if mention_sender or plugin_config.message_action_mention_group_trigger_user:
        return (event.user_id,)

    return ()


async def send_matcher_message(
    matcher: Matcher,
    message: str | Message,
    *,
    at_user_ids: Iterable[int] = (),
) -> None:
    await matcher.send(build_message(message, at_user_ids=at_user_ids))


async def finish_matcher_message(
    matcher: Matcher,
    message: str | Message,
    *,
    at_user_ids: Iterable[int] = (),
) -> None:
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
        )
        await asyncio.sleep(interval_seconds)

    await finish_matcher_message(
        matcher,
        messages[-1],
        at_user_ids=at_user_ids,
    )
