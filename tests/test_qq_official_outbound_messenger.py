from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from ironsbot.core.outbound import (
    DeliveryFailureKind,
    OutboundMessage,
    ReplyContext,
)
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.qq_official.outbound_messenger import (
    QQOfficialOutboundMessenger,
)
from ironsbot.services.messaging.outbound_routing import PlatformOutboundMessenger

if TYPE_CHECKING:
    from nonebot.adapters.qq import Message


@dataclass
class _Bot:
    response_id: str | None = "message-1"
    calls: list[tuple[str, str, Message, str | None, int | None]] = field(
        default_factory=list
    )

    async def send_to_c2c(
        self,
        openid: str,
        message: Message,
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> object:
        self.calls.append(("private", openid, message, msg_id, msg_seq))
        return SimpleNamespace(id=self.response_id)

    async def send_to_group(
        self,
        group_openid: str,
        message: Message,
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> object:
        self.calls.append(("group", group_openid, message, msg_id, msg_seq))
        return SimpleNamespace(id=self.response_id)


GROUP = ConversationRef(Platform.QQ_OFFICIAL, "group", "group-openid")
PRIVATE = ConversationRef(Platform.QQ_OFFICIAL, "private", "user-openid")
TEXT = OutboundMessage.from_text("result")


@pytest.mark.asyncio
async def test_proactive_delivery_is_explicitly_disabled_by_default() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        "app",
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.send(GROUP, TEXT)

    assert not messenger.capabilities_for(GROUP).can_send_proactively
    assert result.error_code == "proactive_disabled"
    assert result.failure_kind is DeliveryFailureKind.PERMANENT
    assert bot.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("conversation", "kind"),
    [(GROUP, "group"), (PRIVATE, "private")],
)
async def test_enabled_proactive_delivery_uses_conversation_target(
    conversation: ConversationRef,
    kind: str,
) -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        "app",
        proactive_enabled=True,
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.send(conversation, TEXT)

    assert result.delivered
    assert bot.calls[0][0:2] == (kind, conversation.id)
    assert bot.calls[0][3:] == (None, None)


@pytest.mark.asyncio
async def test_reply_uses_event_message_id_and_first_reply_sequence() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        "app",
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.reply(ReplyContext(GROUP, "event-id", "event-index"), TEXT)

    assert result.delivered
    assert bot.calls[0][3:] == ("event-id", 1)


@pytest.mark.asyncio
async def test_replies_allocate_unique_sequences_per_event() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        "app",
        bot_provider=lambda _app_id: bot,
    )

    for _ in range(4):
        assert (await messenger.reply(ReplyContext(GROUP, "event-id"), TEXT)).delivered
    exhausted = await messenger.reply(ReplyContext(GROUP, "event-id"), TEXT)
    other = await messenger.reply(ReplyContext(GROUP, "other-event"), TEXT)

    assert [call[4] for call in bot.calls] == [1, 2, 3, 4, 1]
    assert exhausted.error_code == "passive_reply_limit_exceeded"
    assert other.delivered


@pytest.mark.asyncio
async def test_reply_limit_can_fall_back_to_explicitly_enabled_proactive_send() -> None:
    bot = _Bot()
    messenger = QQOfficialOutboundMessenger(
        "app",
        proactive_enabled=True,
        bot_provider=lambda _app_id: bot,
    )

    for _ in range(5):
        result = await messenger.reply(ReplyContext(PRIVATE, "event-id"), TEXT)
        assert result.delivered

    assert [call[3:] for call in bot.calls] == [
        ("event-id", 1),
        ("event-id", 2),
        ("event-id", 3),
        ("event-id", 4),
        (None, None),
    ]


@pytest.mark.asyncio
async def test_unavailable_bot_is_reported_without_attempting_delivery() -> None:
    messenger = QQOfficialOutboundMessenger(
        "app",
        proactive_enabled=True,
        bot_provider=lambda _app_id: None,
    )

    result = await messenger.send(GROUP, TEXT)

    assert result.error_code == "bot_unavailable"
    assert result.failure_kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE


@pytest.mark.asyncio
async def test_missing_response_id_is_an_uncertain_delivery() -> None:
    bot = _Bot(response_id=None)
    messenger = QQOfficialOutboundMessenger(
        "app",
        proactive_enabled=True,
        bot_provider=lambda _app_id: bot,
    )

    result = await messenger.send(GROUP, TEXT)

    assert result.error_code == "missing_message_id"
    assert result.failure_kind is DeliveryFailureKind.UNCERTAIN


@pytest.mark.asyncio
async def test_platform_router_delegates_and_rejects_missing_adapter() -> None:
    bot = _Bot()
    official = QQOfficialOutboundMessenger(
        "app",
        proactive_enabled=True,
        bot_provider=lambda _app_id: bot,
    )
    routed = PlatformOutboundMessenger({Platform.QQ_OFFICIAL: official})
    unsupported = ConversationRef(Platform.ONEBOT, "group", "123")

    delivered = await routed.send(GROUP, TEXT)
    rejected = await routed.send(unsupported, TEXT)

    assert delivered.delivered
    assert rejected.error_code == "unsupported_platform"
    assert rejected.failure_kind is DeliveryFailureKind.PERMANENT
