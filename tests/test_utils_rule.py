import asyncio

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment

from ironsbot.utils.rule import NoAt
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
