import asyncio
from typing import TYPE_CHECKING, Any, cast

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from pytest import MonkeyPatch

from ironsbot.plugins.messaging import red_packet as red_packet_notice_plugin
from ironsbot.plugins.messaging.red_packet import (
    is_red_packet_message,
    is_red_packet_payload,
    summarize_red_packet_message,
)
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.messaging.red_packet import (
    RedPacketNoticeLimiter,
    build_red_packet_notice_message,
)
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot


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


def test_notice_payload_with_red_packet_marker_is_detected() -> None:
    payload = {
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "red_packet",
        "raw_info": [{"txt": "QQ红包"}],
    }

    assert is_red_packet_payload(payload)


def test_notice_payload_with_napcat_red_packet_gray_tip_id_is_detected() -> None:
    payload = {
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "gray_tip",
        "busi_id": "81",
        "content": '{"items":[{"txt":"system message"}]}',
    }

    assert is_red_packet_payload(payload)


def test_notice_payload_without_red_packet_marker_is_not_detected() -> None:
    payload = {
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "poke",
        "raw_info": [{"txt": "戳了戳"}],
    }

    assert not is_red_packet_payload(payload)


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


def test_red_packet_notice_uses_admin_notice_delivery(
    monkeypatch: MonkeyPatch,
) -> None:
    bot = cast("Bot", object())
    calls: list[dict[str, Any]] = []

    async def fake_resolve_group_name(
        _bot: object,
        _group_id: int,
        **_kwargs: object,
    ) -> str:
        return "示例群"

    async def fake_send_admin_notice(
        _service: AdminNoticeService,
        message: object,
        *,
        subscription_key: str,
        action_name: str,
        bot: object | None = None,
        interval_seconds: float = 1.5,
    ) -> object:
        calls.append(
            {
                "message": message,
                "subscription_key": subscription_key,
                "action_name": action_name,
                "bot": bot,
                "interval_seconds": interval_seconds,
            }
        )
        return object()

    monkeypatch.setattr(
        red_packet_notice_plugin,
        "resolve_group_name",
        fake_resolve_group_name,
    )
    monkeypatch.setattr(
        AdminNoticeService,
        "send",
        fake_send_admin_notice,
    )

    asyncio.run(
        red_packet_notice_plugin._send_red_packet_notice(
            bot=bot,
            limiter=RedPacketNoticeLimiter(cooldown_seconds=0.0),
            group_id=987654321,
            sender_id=1234567890,
            summary="恭喜发财",
            admin_notices=build_test_runtime().admin_notices,
        )
    )

    assert len(calls) == 1
    assert calls[0]["subscription_key"] == "red_packet_notice"
    assert calls[0]["action_name"] == "red packet notice"
    assert calls[0]["bot"] is None
    assert "示例群（987654321）" in str(calls[0]["message"])
