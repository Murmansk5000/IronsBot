# SPDX-License-Identifier: GPL-3.0-or-later

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.plugins.seer.query.commands.player_target import (
    resolve_player_target,
)
from tests.helpers.onebot_events import group_message_event

PLAYER_ID = 105_023_264


def _binding_for(user_id: int) -> int | None:
    return {456: PLAYER_ID}.get(user_id)


def test_player_target_uses_one_current_message_member_mention() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("收集"), MessageSegment.at(456)])
    )

    target = resolve_player_target(
        event,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )

    assert target.player_id == PLAYER_ID
    assert not target.offer_binding
    assert target.error is None


def test_player_target_uses_member_mention_sent_after_a_quote() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("收集"), MessageSegment.at(456)]),
        reply_sender_user_id=789,
    )

    target = resolve_player_target(
        event,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )

    assert target.player_id == PLAYER_ID
    assert not target.offer_binding
    assert target.error is None


def test_player_target_member_lookup_does_not_offer_to_bind_another_person() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("群星牌"), MessageSegment.at(456)])
    )

    target = resolve_player_target(
        event,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )

    assert not target.offer_binding


def test_player_target_rejects_ambiguous_member_target_forms() -> None:
    two_members = group_message_event(
        message=Message(
            [
                MessageSegment.text("巅峰"),
                MessageSegment.at(456),
                MessageSegment.at(789),
            ]
        )
    )
    member_and_number = group_message_event(
        message=Message([MessageSegment.text("收集712345678"), MessageSegment.at(456)])
    )

    multiple = resolve_player_target(
        two_members,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )
    mixed = resolve_player_target(
        member_and_number,
        numeric_player_id=105_023_264,
        binding_for_user=_binding_for,
    )

    assert multiple.error == "请一次只 @ 一名成员查询其已绑定的米米号。"
    assert mixed.error == "米米号数字和 @成员 不能同时使用，请保留其中一种。"


def test_player_target_reports_an_unbound_mentioned_member() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("米米号"), MessageSegment.at(789)])
    )

    target = resolve_player_target(
        event,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )

    assert target.player_id is None
    assert target.error == "该成员尚未绑定米米号。"
