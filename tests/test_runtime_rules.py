# SPDX-License-Identifier: MIT
import asyncio
from typing import cast

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from ironsbot.runtime.rules import (
    CommandInput,
    DirectMessageOnly,
    MessageInputRoute,
    command_input,
    direct_message_only,
    message_input_route,
)
from tests.helpers.onebot_events import group_message_event


def _matches_command_input(
    event: GroupMessageEvent,
    *,
    allow_direct_mentions: bool = False,
) -> bool:
    return asyncio.run(
        CommandInput(allow_direct_mentions=allow_direct_mentions)(event, {})
    )


def _matches_direct_message(event: GroupMessageEvent) -> bool:
    return asyncio.run(DirectMessageOnly()(event, {}))


def test_direct_plain_text_is_a_command_input() -> None:
    event = group_message_event(message=Message("帮助"))

    assert message_input_route(event) is MessageInputRoute.DIRECT_COMMAND
    assert _matches_command_input(event)
    assert _matches_direct_message(event)


def test_direct_mentions_are_reserved_for_the_mention_route() -> None:
    event = group_message_event(
        message=Message(
            [
                MessageSegment.at(2947993138),
                MessageSegment.text("帮助"),
            ]
        )
    )

    assert message_input_route(event) is MessageInputRoute.DIRECT_MENTION
    assert not _matches_command_input(event)
    assert not _matches_direct_message(event)
    assert _matches_command_input(event, allow_direct_mentions=True)


def test_reply_has_priority_over_mentions_and_is_a_command_input() -> None:
    event = group_message_event(
        message=Message(
            [
                MessageSegment.at(2947993138),
                MessageSegment.text("帮助"),
            ]
        ),
        reply_sender_user_id=456,
    )

    assert message_input_route(event) is MessageInputRoute.REPLY_COMMAND
    assert _matches_command_input(event)
    assert not _matches_direct_message(event)


def test_command_input_rule_exposes_same_priority_policy() -> None:
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
    assert asyncio.run(
        command_input(allow_direct_mentions=True)(bot, mentioned_event, {})
    )
    assert asyncio.run(command_input()(bot, replied_event, {}))
    assert not asyncio.run(direct_message_only()(bot, replied_event, {}))
