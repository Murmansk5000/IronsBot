import asyncio
from typing import Any
from unittest.mock import Mock

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from pytest import MonkeyPatch

from ironsbot.config.models.messaging import RedPacketNoticeConfig
from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.plugins.onebot.messaging.red_packet import (
    is_red_packet_message,
    is_red_packet_payload,
    summarize_red_packet_message,
)
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.messaging.red_packet import (
    RedPacketNoticeService,
    build_red_packet_notice_message,
)
from tests.helpers.runtime import build_test_runtime


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
        conversation=ConversationRef(Platform.ONEBOT, "group", "987654321"),
        conversation_name="示例群",
        sender=ActorRef(Platform.ONEBOT, "1234567890"),
        summary="恭喜发财",
    )

    assert "检测到群红包" in notice
    assert "示例群（987654321）" in notice
    assert "发送者：1234567890" in notice
    assert "内容：恭喜发财" in notice


def test_red_packet_notice_limiter_uses_per_group_cooldown() -> None:
    service = RedPacketNoticeService(RedPacketNoticeConfig(), Mock())
    first = CommandContext(
        ActorRef(Platform.ONEBOT, "123"),
        ConversationRef(Platform.ONEBOT, "group", "1"),
    )
    second = CommandContext(first.actor, ConversationRef(Platform.ONEBOT, "group", "2"))

    assert service.admit(first, now=100.0)
    assert not service.admit(first, now=120.0)
    assert service.admit(second, now=120.0)
    assert not service.admit(first, now=159.0)
    assert service.admit(first, now=160.0)


def test_red_packet_notice_limiter_keeps_platforms_separate() -> None:
    service = RedPacketNoticeService(RedPacketNoticeConfig(), Mock())
    for platform in Platform:
        context = CommandContext(
            ActorRef(platform, "123"), ConversationRef(platform, "group", "1")
        )
        assert service.admit(context, now=100.0)


def test_red_packet_notice_uses_admin_notice_delivery(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_resolve_group_name() -> str:
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
        AdminNoticeService,
        "send",
        fake_send_admin_notice,
    )

    asyncio.run(
        RedPacketNoticeService(
            RedPacketNoticeConfig(cooldown_seconds=0),
            build_test_runtime().admin_notices,
        ).handle(
            CommandContext(
                ActorRef(Platform.ONEBOT, "1234567890"),
                ConversationRef(Platform.ONEBOT, "group", "987654321"),
            ),
            summary="恭喜发财",
            conversation_name=fake_resolve_group_name,
        )
    )

    assert len(calls) == 1
    assert calls[0]["subscription_key"] == "red_packet_notice"
    assert calls[0]["action_name"] == "red packet notice"
    assert calls[0]["bot"] is None
    assert "示例群（987654321）" in str(calls[0]["message"])
