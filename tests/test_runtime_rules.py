import asyncio
from typing import cast

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from ironsbot.runtime.rules import NoAt, no_reply
from tests.helpers.onebot_events import group_message_event


def _matches_no_at(event: GroupMessageEvent) -> bool:
    return asyncio.run(NoAt()(event, {}))


def test_no_at_allows_plain_text_messages() -> None:
    assert _matches_no_at(group_message_event(message=Message("帮助")))


def test_no_at_blocks_direct_bot_mentions() -> None:
    assert not _matches_no_at(
        group_message_event(
            message=Message(
                [
                    MessageSegment.at(2947993138),
                    MessageSegment.text("帮助"),
                ]
            )
        )
    )


def test_no_at_blocks_foreign_mentions() -> None:
    assert not _matches_no_at(
        group_message_event(
            message=Message(
                [
                    MessageSegment.at(123),
                    MessageSegment.text("帮助"),
                ]
            )
        )
    )


def test_no_at_blocks_onebot_at_segments() -> None:
    event = group_message_event(message=Message("[CQ:at,qq=2947993138] 帮助"))

    assert not _matches_no_at(event)


def test_no_reply_can_allow_mentions_but_blocks_reply_messages() -> None:
    mentioned_event = group_message_event(
        message=Message(
            [
                MessageSegment.text("订阅战队1234567 1000 "),
                MessageSegment.at(123),
            ]
        )
    )
    replied_event = group_message_event(
        message=mentioned_event.message,
        reply_sender_user_id=456,
    )

    bot = cast("Bot", None)
    assert not asyncio.run(no_reply()(bot, mentioned_event, {}))

    rule = no_reply(allow_at=True)
    assert asyncio.run(rule(bot, mentioned_event, {}))
    assert not asyncio.run(rule(bot, replied_event, {}))
