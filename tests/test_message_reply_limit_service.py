import nonebot
from nonebot.adapters.onebot.v11 import Message, MessageSegment

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.shared.messaging.reply_limits import (
    build_reply_line_limit_decision,
    group_id_for_send_api,
    limit_onebot_message,
    limit_text_lines,
    parse_reply_line_limit_arg,
)

SET_LIMIT = 20
GROUP_ID_TEXT = "123"
GROUP_ID = 123
OTHER_GROUP_ID = 456


def test_parse_reply_line_limit_arg_prefers_long_prefix() -> None:
    assert parse_reply_line_limit_arg("设置回复行数 20") == "20"
    assert parse_reply_line_limit_arg("回复行数 -1") == "-1"
    assert parse_reply_line_limit_arg("不是指令") is None


def test_reply_line_limit_decision_shows_current_limit() -> None:
    decision = build_reply_line_limit_decision(
        raw_arg="",
        current_limit=None,
        can_manage=True,
        min_lines=5,
        max_allowed_lines=80,
    )

    assert decision.message == (
        "当前本群回复消息行数：不限制\n"
        "用法：/回复行数 20；发送 /回复行数 -1 可恢复默认。"
    )
    assert not decision.should_clear
    assert not decision.should_set


def test_reply_line_limit_decision_rejects_non_admin() -> None:
    decision = build_reply_line_limit_decision(
        raw_arg=str(SET_LIMIT),
        current_limit=10,
        can_manage=False,
        min_lines=5,
        max_allowed_lines=80,
    )

    assert decision.message == "只有本群群主、管理员或超级管理员可以修改回复行数。"
    assert not decision.should_set


def test_reply_line_limit_decision_clears_limit() -> None:
    decision = build_reply_line_limit_decision(
        raw_arg="-1",
        current_limit=10,
        can_manage=True,
        min_lines=5,
        max_allowed_lines=80,
    )

    assert decision.message == "已恢复本群回复消息行数默认设置。"
    assert decision.should_clear
    assert not decision.should_set


def test_reply_line_limit_decision_validates_range() -> None:
    decision = build_reply_line_limit_decision(
        raw_arg="3",
        current_limit=10,
        can_manage=True,
        min_lines=5,
        max_allowed_lines=80,
    )

    assert decision.message == "回复行数范围是 5 ~ 80。"
    assert not decision.should_set


def test_reply_line_limit_decision_sets_limit() -> None:
    decision = build_reply_line_limit_decision(
        raw_arg="20",
        current_limit=10,
        can_manage=True,
        min_lines=5,
        max_allowed_lines=80,
    )

    assert decision.message == "已设置本群回复消息行数：20 行。"
    assert decision.max_lines == SET_LIMIT
    assert decision.should_set


def test_limit_text_lines_appends_hidden_count() -> None:
    assert limit_text_lines("1\n2\n3", 2) == "1\n...还有 2 行未显示"


def test_limit_onebot_message_keeps_at_and_limits_text() -> None:
    message = MessageSegment.at(123) + MessageSegment.text(" 1\n2\n3")

    limited = limit_onebot_message(message, max_lines=2)

    assert isinstance(limited, Message)
    assert limited[0].type == "at"
    assert str(limited).endswith("1\n...还有 2 行未显示")


def test_limit_onebot_message_skips_non_text_segments() -> None:
    message = MessageSegment.image("https://example.com/a.png")

    assert limit_onebot_message(message, max_lines=1) == message


def test_group_id_for_send_api_only_reads_group_targets() -> None:
    assert (
        group_id_for_send_api("send_group_msg", {"group_id": GROUP_ID_TEXT})
        == GROUP_ID
    )
    assert group_id_for_send_api(
        "send_msg",
        {"message_type": "group", "group_id": OTHER_GROUP_ID},
    ) == OTHER_GROUP_ID
    assert group_id_for_send_api(
        "send_msg",
        {"message_type": "private", "group_id": OTHER_GROUP_ID},
    ) is None
