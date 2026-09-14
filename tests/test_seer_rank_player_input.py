# SPDX-License-Identifier: GPL-3.0-or-later

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.plugins.onebot.seer.query.commands import rank_list
from tests.helpers.onebot_events import group_message_event

PRIVATE_GROUP_ID = 987_654_321


def test_rank_player_rule_recognizes_an_alias_target() -> None:
    assert rank_list._is_rank_player_command(
        group_message_event("成就榜示例玩家", group_id=PRIVATE_GROUP_ID),
    )


def test_rank_player_rule_recognizes_one_direct_member_mention() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("群星牌榜"), MessageSegment.at(456)]),
        group_id=PRIVATE_GROUP_ID,
    )

    assert rank_list._is_rank_player_command(event)


def test_rank_player_rule_admits_mixed_input_for_shared_error_reply() -> None:
    event = group_message_event(
        message=Message(
            [MessageSegment.text("成就榜示例玩家"), MessageSegment.at(456)]
        ),
        group_id=PRIVATE_GROUP_ID,
    )

    assert rank_list._is_rank_player_command(event)
