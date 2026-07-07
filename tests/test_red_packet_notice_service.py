from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.services.red_packet_notice import (
    RedPacketNoticeLimiter,
    build_red_packet_notice_message,
    is_red_packet_message,
    summarize_red_packet_message,
)


def test_red_packet_segment_is_detected() -> None:
    message = Message([MessageSegment("redbag", {"title": "恭喜发财"})])

    assert is_red_packet_message(message)
    assert summarize_red_packet_message(message) == "恭喜发财"


def test_qq_red_packet_system_text_is_detected() -> None:
    message = Message("[QQ红包]恭喜发财，大吉大利")

    assert is_red_packet_message(message)


def test_plain_red_packet_chat_is_not_detected() -> None:
    message = Message("谁发个红包")

    assert not is_red_packet_message(message)


def test_build_red_packet_notice_message_includes_group_and_sender() -> None:
    notice = build_red_packet_notice_message(
        group_id=987654321,
        group_name="示例群",
        sender_id=1234567890,
        summary="恭喜发财",
    )

    assert "检测到群红包" in notice
    assert "示例群（987654321）" in notice
    assert "发送者：1234567890" in notice
    assert "内容：恭喜发财" in notice


def test_red_packet_notice_limiter_uses_per_group_cooldown() -> None:
    limiter = RedPacketNoticeLimiter(cooldown_seconds=60.0)

    assert limiter.can_send(1, now=100.0)
    assert not limiter.can_send(1, now=120.0)
    assert limiter.can_send(2, now=120.0)
    assert limiter.can_send(1, now=161.0)
