import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import nonebot
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from pytest import MonkeyPatch

from ironsbot.services.red_packet_notice import (
    RedPacketNoticeLimiter,
    build_red_packet_notice_message,
    is_red_packet_message,
    is_red_packet_payload,
    summarize_red_packet_message,
)
from ironsbot.shared import matcher_priority

_PLUGIN_PATH = (
    Path(__file__).parents[1]
    / "ironsbot"
    / "plugins"
    / "red_packet_notice"
    / "__init__.py"
)


class _DummyMatcher:
    def handle(self) -> Any:
        def _decorator(func: Any) -> Any:
            return func

        return _decorator


def _load_red_packet_notice_plugin(monkeypatch: MonkeyPatch) -> Any:
    def _dummy_on_event(*_args: Any, **_kwargs: Any) -> _DummyMatcher:
        return _DummyMatcher()

    monkeypatch.setattr(nonebot, "on_message", _dummy_on_event)
    monkeypatch.setattr(nonebot, "on_notice", _dummy_on_event)
    monkeypatch.setattr(matcher_priority, "get_matcher_priority", lambda *_args: 1)

    spec = spec_from_file_location("red_packet_notice_plugin_for_test", _PLUGIN_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    plugin = _load_red_packet_notice_plugin(monkeypatch)
    bot = object()
    calls: list[dict[str, Any]] = []

    async def fake_get_group_name(_bot: object, _group_id: int) -> str:
        return "示例群"

    async def fake_send_admin_notice(
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

    monkeypatch.setattr(plugin, "_get_group_name", fake_get_group_name)
    monkeypatch.setattr(
        plugin,
        "_get_limiter",
        lambda: RedPacketNoticeLimiter(cooldown_seconds=0.0),
    )
    monkeypatch.setattr(plugin, "send_admin_notice", fake_send_admin_notice)

    asyncio.run(
        plugin._send_red_packet_notice(
            bot=bot,
            group_id=987654321,
            sender_id=1234567890,
            summary="恭喜发财",
        )
    )

    assert len(calls) == 1
    assert calls[0]["subscription_key"] == "red_packet_notice"
    assert calls[0]["action_name"] == "red packet notice"
    assert calls[0]["bot"] is bot
    assert "示例群（987654321）" in str(calls[0]["message"])
