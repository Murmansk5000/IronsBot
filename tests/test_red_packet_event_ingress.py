from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import (
    Adapter,
    Bot,
    Message,
    MessageSegment,
    NoticeEvent,
)
from nonebot.message import handle_event

from ironsbot.config.models.messaging import RedPacketNoticeConfig
from ironsbot.config.models.settings import MatcherPriorityConfig
from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot import red_packet as packet_protocol
from ironsbot.integrations.onebot.notice_ingress import OneBotNoticeIngress
from ironsbot.integrations.onebot.received_messages import OneBotReceivedMessages
from ironsbot.plugins.onebot.messaging import red_packet
from ironsbot.services.messaging.admin_notice import (
    AdminNoticeSendSummary,
    AdminNoticeService,
)
from ironsbot.services.messaging.red_packet import RedPacketNoticeService
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from types import SimpleNamespace

pytest_plugins = ("tests.test_shared_onebot_ingress",)


def _context(platform: Platform, *, private: bool = False) -> CommandContext:
    return CommandContext(
        ActorRef(platform, "101"),
        ConversationRef(
            platform, "private" if private else "group", "101" if private else "456"
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("enabled,private", [(False, False), (True, True)])
async def test_disabled_or_private_red_packet_skips_lookup_and_delivery(
    platform: Platform, *, enabled: bool, private: bool
) -> None:
    notices = Mock(send=AsyncMock())
    name = AsyncMock(return_value="group")
    service = RedPacketNoticeService(RedPacketNoticeConfig(enabled=enabled), notices)
    assert (
        await service.handle(
            _context(platform, private=private),
            summary="red packet",
            conversation_name=name,
        )
        is None
    )
    name.assert_not_awaited()
    notices.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_concurrent_red_packet_sources_share_admission_before_lookup(
    platform: Platform,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def name() -> str:
        entered.set()
        await release.wait()
        return "group"

    failed = AdminNoticeSendSummary((), (_context(platform).conversation,))
    notices = Mock(send=AsyncMock(return_value=failed))
    service = RedPacketNoticeService(RedPacketNoticeConfig(), notices)
    first = asyncio.create_task(
        service.handle(_context(platform), summary="message", conversation_name=name)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert (
            await service.handle(
                _context(platform), summary="notice", conversation_name=name
            )
            is None
        )
        release.set()
        assert await first is failed
        assert (
            await service.handle(
                _context(platform), summary="replayed notice", conversation_name=name
            )
            is None
        )
        notices.send.assert_awaited_once()
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)


@pytest.mark.asyncio
async def test_red_packet_cancellation_retains_admission_window() -> None:
    entered = asyncio.Event()

    async def name() -> str:
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    notices = Mock(send=AsyncMock())
    service = RedPacketNoticeService(RedPacketNoticeConfig(), notices)
    first = asyncio.create_task(
        service.handle(
            _context(Platform.ONEBOT), summary="message", conversation_name=name
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (
            await service.handle(
                _context(Platform.ONEBOT), summary="notice", conversation_name=name
            )
            is None
        )
        notices.send.assert_not_awaited()
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)


@pytest.mark.asyncio
async def test_zero_cooldown_keeps_existing_unlimited_semantics() -> None:
    notices = Mock(send=AsyncMock(return_value=AdminNoticeSendSummary((), ())))
    name = AsyncMock(return_value="group")
    service = RedPacketNoticeService(RedPacketNoticeConfig(cooldown_seconds=0), notices)
    for summary in ("message", "notice"):
        await service.handle(
            _context(Platform.ONEBOT), summary=summary, conversation_name=name
        )
    assert notices.send.await_count == len(("message", "notice"))


@pytest.mark.asyncio
@pytest.mark.parametrize("notice_first", [False, True])
@pytest.mark.parametrize("lookup_failure", [False, True])
@pytest.mark.parametrize("source", ["native", "raw"])
async def test_actual_dual_sources_send_only_to_configured_admin_targets(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    notice_first: bool,
    lookup_failure: bool,
    source: str,
) -> None:
    private_admin = ActorRef(Platform.ONEBOT, "303")
    admin_group = ConversationRef(Platform.ONEBOT, "group", "204")
    ordinary_group = _context(Platform.ONEBOT).conversation
    sender = Mock(
        send_admin_notice=AsyncMock(
            return_value=AdminNoticeSendSummary((private_admin, admin_group), ())
        )
    )
    features = FeatureService(
        {admin_group: frozenset({"admin_notice"}), ordinary_group: frozenset({"help"})},
        {private_admin: frozenset({"admin_notice"})},
        frozenset(),
    )
    service = RedPacketNoticeService(
        RedPacketNoticeConfig(), AdminNoticeService(features, sender)
    )
    calls: list[str] = []

    async def api(_adapter: Adapter, _bot: Bot, name: str, **_data: Any) -> object:
        calls.append(name)
        assert name == "get_group_info"
        if lookup_failure:
            raise RuntimeError("sensitive-source-error")
        return {"group_name": "example group"}

    monkeypatch.setattr(Adapter, "_call_api", api)
    debug = Mock()
    monkeypatch.setattr(packet_protocol.logger, "debug", debug)
    runtime.factory.priorities.red_packet_notice = 0
    red_packet.install(runtime.factory, service)
    message = group_message_event(
        message=Message([MessageSegment("redbag", {"title": "packet"})]), user_id=101
    )
    notice = NoticeEvent.model_validate(
        {
            "time": 0,
            "self_id": 1,
            "post_type": "notice",
            "notice_type": "notify",
            "sub_type": "red_packet",
            "group_id": 456,
            "user_id": 101,
        }
    )
    events = (notice, message) if notice_first else (message, notice)
    messages = OneBotReceivedMessages(
        runtime.admission,
        runtime.router,
        runtime.messenger,
        red_packets=service,
    )
    notices = OneBotNoticeIngress(
        runtime.admission,
        runtime.messenger,
        Mock(),
        MatcherPriorityConfig(),
        red_packets=service,
    )
    for event in events:
        if source == "native":
            await handle_event(runtime.bot, event)
        elif isinstance(event, NoticeEvent):
            await notices.handle(runtime.bot, event.model_dump())
        else:
            await messages.handle(runtime.bot, event.model_dump())

    assert calls == ["get_group_info"]
    sender.send_admin_notice.assert_awaited_once()
    kwargs = sender.send_admin_notice.call_args.kwargs
    assert kwargs["private_actors"] == (private_admin,)
    assert kwargs["group_conversations"] == (admin_group,)
    assert kwargs["subscription_key"] == "red_packet_notice"
    assert kwargs["action_name"] == "red packet notice"
    text = sender.send_admin_notice.call_args.args[0].parts[0].text
    assert ("example group" in text) is not lookup_failure
    assert "sensitive-source-error" not in str(debug.call_args_list)
    assert runtime.sends == []
