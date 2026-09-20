from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.config.models.messaging import OutboundRateLimitConfig
from ironsbot.core.outbound import (
    BinaryImagePart,
    DeliveryFailureKind,
    MentionPart,
    OutboundMessage,
    ReplyContext,
    TextPart,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.outbound import OutboundRateLimitDecision
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message


GROUP_ID = 1001
MENTIONED_USER_ID = 2002


@dataclass
class _Bot:
    private_messages: list[tuple[int, Message]] = field(default_factory=list)
    group_messages: list[tuple[int, Message]] = field(default_factory=list)

    async def send_private_msg(self, *, user_id: int, message: Message) -> object:
        self.private_messages.append((user_id, message))
        return {"message_id": 101}

    async def send_group_msg(self, *, group_id: int, message: Message) -> object:
        self.group_messages.append((group_id, message))
        return {"message_id": 202}


@dataclass
class _Router:
    bot: _Bot | None

    def for_conversation(self, _conversation: ConversationRef) -> _Bot | None:
        return self.bot


def _messenger(bot: _Bot | None = None) -> OneBotOutboundMessenger:
    runtime = build_test_runtime(
        outbound_config=OutboundRateLimitConfig(enabled=False),
    )
    return OneBotOutboundMessenger(
        cast("Any", _Router(bot)),
        runtime.outbound,
    )


@pytest.mark.asyncio
async def test_onebot_outbound_messenger_sends_group_message_with_mention() -> None:
    bot = _Bot()
    result = await _messenger(bot).send(
        ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID)),
        OutboundMessage(
            (
                MentionPart(ActorRef(Platform.ONEBOT, str(MENTIONED_USER_ID))),
                TextPart("hello"),
                BinaryImagePart(b"png", "image/png"),
            )
        ),
    )

    assert result.delivered
    assert result.message_id == "202"
    assert bot.group_messages[0][0] == GROUP_ID
    assert str(bot.group_messages[0][1]).startswith(
        f"[CQ:at,qq={MENTIONED_USER_ID}]hello"
    )
    assert "base64://cG5n" in str(bot.group_messages[0][1])


@pytest.mark.asyncio
async def test_onebot_outbound_messenger_replies_with_message_reference() -> None:
    bot = _Bot()
    result = await _messenger(bot).reply(
        ReplyContext(ConversationRef(Platform.ONEBOT, "private", "1001"), "99"),
        OutboundMessage((TextPart("hello"),)),
    )

    assert result.delivered
    assert str(bot.private_messages[0][1]).startswith("[CQ:reply,id=99]hello")


@pytest.mark.asyncio
async def test_onebot_outbound_messenger_rejects_unsupported_conversation() -> None:
    messenger = _messenger()
    result = await messenger.send(
        ConversationRef(Platform.QQ_OFFICIAL, "group", "1001"),
        OutboundMessage((TextPart("hello"),)),
    )

    assert not result.delivered
    assert result.error_code == "unsupported_conversation"
    assert result.failure_kind is DeliveryFailureKind.PERMANENT
    assert not messenger.capabilities_for(
        ConversationRef(Platform.QQ_OFFICIAL, "group", "1001")
    ).can_send_proactively


@pytest.mark.asyncio
async def test_onebot_outbound_messenger_rejects_all_sends_when_disabled() -> None:
    bot = _Bot()
    runtime = build_test_runtime(
        outbound_config=OutboundRateLimitConfig(enabled=False),
    )
    messenger = OneBotOutboundMessenger(
        cast("Any", _Router(bot)),
        runtime.outbound,
        enabled=False,
    )
    conversation = ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID))

    proactive = await messenger.send(
        conversation,
        OutboundMessage((TextPart("hello"),)),
    )
    reply = await messenger.reply(
        ReplyContext(conversation, "99"),
        OutboundMessage((TextPart("hello"),)),
    )

    assert not messenger.capabilities_for(conversation).can_reply_to_event
    assert not messenger.capabilities_for(conversation).can_send_proactively
    assert proactive.error_code == "outbound_disabled"
    assert reply.error_code == "outbound_disabled"
    assert bot.group_messages == []


@pytest.mark.asyncio
async def test_onebot_outbound_messenger_marks_disconnected_route() -> None:
    result = await _messenger().send(
        ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID)),
        OutboundMessage((TextPart("hello"),)),
    )

    assert not result.delivered
    assert result.failure_kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE


@pytest.mark.asyncio
async def test_onebot_outbound_messenger_drops_rate_limited_proactive_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _Bot()
    runtime = build_test_runtime(
        outbound_config=OutboundRateLimitConfig(enabled=False),
    )

    async def reject_push(
        group_id: int | None,
        *,
        source: str,
    ) -> OutboundRateLimitDecision:
        assert group_id == GROUP_ID
        assert source == "platform outbound"
        return OutboundRateLimitDecision(allowed=False, reason="rate_limit")

    monkeypatch.setattr(runtime.outbound, "acquire_push", reject_push)
    messenger = OneBotOutboundMessenger(
        cast("Any", _Router(bot)),
        runtime.outbound,
    )

    result = await messenger.send(
        ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID)),
        OutboundMessage((TextPart("hello"),)),
    )

    assert not result.delivered
    assert result.error_code == "rate_limit"
    assert result.failure_kind is DeliveryFailureKind.RETRYABLE
    assert bot.group_messages == []
