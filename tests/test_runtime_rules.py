# SPDX-License-Identifier: MIT
import asyncio
from typing import cast

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.rule import Rule

from ironsbot.runtime.message_input import (
    MessageInputKind,
    message_input_context,
)
from ironsbot.runtime.rules import (
    bot_mention,
    explicit_command,
    member_target_command,
    member_targets_command,
    natural_language,
)
from tests.helpers.onebot_events import group_message_event


def _matches(rule: Rule, event: Event) -> bool:
    return asyncio.run(rule(cast("Bot", None), event, {}))


def _mentioned_message(*, bot_id: int = 1) -> Message:
    return Message(
        [
            MessageSegment.at(bot_id),
            MessageSegment.at(456),
            MessageSegment.text("帮助"),
        ]
    )


def test_message_input_context_uses_fixed_routing_precedence() -> None:
    direct = group_message_event("帮助")
    member = group_message_event(
        message=Message([MessageSegment.at(456), MessageSegment.text("帮助")])
    )
    bot = group_message_event(message=_mentioned_message())
    reply = group_message_event(
        message=_mentioned_message(),
        reply_sender_user_id=789,
    )

    assert message_input_context(direct).kind is MessageInputKind.DIRECT
    assert message_input_context(member).kind is MessageInputKind.MEMBER_MENTION
    assert message_input_context(bot).kind is MessageInputKind.BOT_MENTION
    assert message_input_context(reply).kind is MessageInputKind.REPLY


def test_explicit_commands_accept_replies_but_not_current_member_mentions() -> None:
    plain = group_message_event("帮助")
    direct_member = group_message_event(
        message=Message([MessageSegment.at(456), MessageSegment.text("帮助")])
    )
    direct_bot = group_message_event(message=_mentioned_message())
    reply_with_bot = group_message_event(
        message=Message([MessageSegment.at(1), MessageSegment.text("帮助")]),
        reply_sender_user_id=789,
    )
    reply_with_member = group_message_event(
        message=Message([MessageSegment.at(456), MessageSegment.text("帮助")]),
        reply_sender_user_id=789,
    )

    assert _matches(explicit_command(), plain)
    assert not _matches(explicit_command(), direct_member)
    assert not _matches(explicit_command(), direct_bot)
    assert _matches(explicit_command(), reply_with_bot)
    assert not _matches(explicit_command(), reply_with_member)


def test_member_target_strategies_are_the_only_member_mention_opt_in() -> None:
    direct_member = group_message_event(
        message=Message([MessageSegment.text("收集"), MessageSegment.at(456)])
    )
    two_members = group_message_event(
        message=Message(
            [
                MessageSegment.text("订阅战队123"),
                MessageSegment.at(456),
                MessageSegment.at(789),
            ]
        )
    )
    direct_bot_and_member = group_message_event(message=_mentioned_message())
    reply_member = group_message_event(
        message=Message([MessageSegment.text("收集"), MessageSegment.at(456)]),
        reply_sender_user_id=789,
    )

    assert _matches(member_target_command(), direct_member)
    assert _matches(member_targets_command(), two_members)
    assert _matches(member_target_command(), reply_member)
    assert not _matches(member_target_command(), direct_bot_and_member)
    assert not _matches(member_targets_command(), direct_bot_and_member)


def test_bot_mentions_and_natural_language_have_disjoint_routes() -> None:
    direct = group_message_event("你好")
    direct_bot = group_message_event(
        message=Message([MessageSegment.at(1), MessageSegment.text("你好")])
    )
    reply_bot = group_message_event(
        message=Message([MessageSegment.at(1), MessageSegment.text("帮助")]),
        reply_sender_user_id=789,
    )

    assert _matches(natural_language(), direct)
    assert not _matches(natural_language(), direct_bot)
    assert not _matches(natural_language(), reply_bot)
    assert _matches(bot_mention(), direct_bot)
    assert not _matches(bot_mention(), reply_bot)
