import asyncio
from typing import cast

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from ironsbot.runtime.rules import NoAt, command_input, direct_message_only
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


def test_command_input_blocks_direct_mentions_but_accepts_replied_commands() -> None:
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
    assert not asyncio.run(command_input()(bot, mentioned_event, {}))
    assert asyncio.run(command_input()(bot, replied_event, {}))


def test_direct_message_only_rejects_mentions_and_replies() -> None:
    mentioned_event = group_message_event(
        message=Message(
            [
                MessageSegment.text("帮"),
                MessageSegment.at(123),
                MessageSegment.text("助"),
            ]
        )
    )
    replied_event = group_message_event("帮助", reply_sender_user_id=456)

    bot = cast("Bot", None)
    rule = direct_message_only()
    assert not asyncio.run(rule(bot, mentioned_event, {}))
    assert not asyncio.run(rule(bot, replied_event, {}))
    assert asyncio.run(rule(bot, group_message_event("帮助"), {}))
