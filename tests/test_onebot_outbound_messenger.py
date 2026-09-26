from __future__ import annotations

import asyncio
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
from ironsbot.integrations.onebot.outbound import (
    OutboundPermit,
    OutboundRateLimitDecision,
)
from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message


GROUP_ID = 1001
MENTIONED_USER_ID = 2002
TIMEOUT_ATTEMPTS = 2
RECOVERY_ATTEMPTS = 3


@dataclass
class _Bot:
    self_id: str = "123456"
    private_messages: list[tuple[int, Message]] = field(default_factory=list)
    group_messages: list[tuple[int, Message]] = field(default_factory=list)

    async def get_login_info(self) -> dict[str, str]:
        return {"nickname": "执行机器人"}

    async def send_private_msg(self, *, user_id: int, message: Message) -> object:
        self.private_messages.append((user_id, message))
        return {"message_id": 101}

    async def send_group_msg(self, *, group_id: int, message: Message) -> object:
        self.group_messages.append((group_id, message))
        return {"message_id": 202}


@dataclass
class _FlakyBot(_Bot):
    failure: Exception | None = None
    attempts: int = 0

    async def send_group_msg(self, *, group_id: int, message: Message) -> object:
        self.attempts += 1
        if self.failure is not None:
            error = self.failure
            self.failure = None
            raise error
        return await super().send_group_msg(group_id=group_id, message=message)


@dataclass
class _ConcurrentBot(_Bot):
    active: int = 0
    max_active: int = 0

    async def send_group_msg(self, *, group_id: int, message: Message) -> object:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return await super().send_group_msg(group_id=group_id, message=message)
        finally:
            self.active -= 1


@dataclass
class _Router:
    bot: _Bot | None
    allowed: bool = True

    def allows_outbound(self, _conversation: ConversationRef) -> bool:
        return self.allowed

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
    assert result.execution_identity is not None
    assert result.execution_identity.account_id == bot.self_id
    assert result.execution_identity.display_name == "执行机器人"
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


@pytest.mark.asyncio
async def test_onebot_outbound_messenger_requires_message_receipt() -> None:
    class NoReceiptBot(_Bot):
        async def send_group_msg(self, *, group_id: int, message: Message) -> object:
            self.group_messages.append((group_id, message))
            return {}

    bot = NoReceiptBot()
    result = await _messenger(bot).send(
        ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID)),
        OutboundMessage((TextPart("hello"),)),
    )

    assert len(bot.group_messages) == 1
    assert not result.delivered
    assert result.failure_kind is DeliveryFailureKind.UNCERTAIN
    assert result.error_code == "missing_message_id"


@pytest.mark.asyncio
async def test_onebot_timeout_is_uncertain_without_opening_circuit() -> None:
    bot = _FlakyBot(failure=TimeoutError("send timed out"))
    messenger = _messenger(bot)
    conversation = ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID))
    message = OutboundMessage((TextPart("hello"),))

    first = await messenger.send(conversation, message)
    second = await messenger.send(conversation, message)

    assert first.failure_kind is DeliveryFailureKind.UNCERTAIN
    assert second.delivered
    assert bot.attempts == TIMEOUT_ATTEMPTS


@pytest.mark.asyncio
async def test_onebot_transport_circuit_is_per_account_and_reply_can_recover() -> None:
    bot = _FlakyBot(failure=ConnectionError("connection closed"))
    other = _FlakyBot(self_id="654321")
    router = _Router(bot)
    runtime = build_test_runtime(
        outbound_config=OutboundRateLimitConfig(enabled=False),
    )
    messenger = OneBotOutboundMessenger(
        cast("Any", router),
        runtime.outbound,
        transport_failure_cooldown_seconds=60,
    )
    conversation = ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID))
    message = OutboundMessage((TextPart("hello"),))

    first = await messenger.send(conversation, message)
    blocked = await messenger.send(conversation, message)
    router.bot = other
    independent = await messenger.send(conversation, message)
    router.bot = bot
    recovered = await messenger.reply(ReplyContext(conversation, "99"), message)
    after_recovery = await messenger.send(conversation, message)

    assert first.failure_kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE
    assert not blocked.attempted
    assert blocked.error_code == "transport_circuit_open"
    assert independent.delivered
    assert recovered.delivered
    assert after_recovery.delivered
    assert bot.attempts == RECOVERY_ATTEMPTS
    assert other.attempts == 1


@pytest.mark.asyncio
async def test_onebot_proactive_sends_are_serialized_per_account() -> None:
    bot = _ConcurrentBot()
    messenger = _messenger(bot)
    message = OutboundMessage((TextPart("hello"),))

    results = await asyncio.gather(
        messenger.send(ConversationRef(Platform.ONEBOT, "group", "1001"), message),
        messenger.send(ConversationRef(Platform.ONEBOT, "group", "1002"), message),
    )

    assert all(result.delivered for result in results)
    assert bot.max_active == 1


@pytest.mark.asyncio
async def test_onebot_uncertain_send_keeps_reserved_rate_limit_permit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _FlakyBot(failure=TimeoutError())
    runtime = build_test_runtime(
        outbound_config=OutboundRateLimitConfig(enabled=False),
    )
    permit = OutboundPermit(token=1, group_id=GROUP_ID, reserved_at=0)
    rollbacks: list[OutboundPermit | None] = []

    async def acquire_push(
        _group_id: int | None,
        *,
        source: str,
    ) -> OutboundRateLimitDecision:
        assert source == "platform outbound"
        return OutboundRateLimitDecision(allowed=True, permit=permit)

    monkeypatch.setattr(runtime.outbound, "acquire_push", acquire_push)
    monkeypatch.setattr(runtime.outbound, "rollback", rollbacks.append)
    messenger = OneBotOutboundMessenger(cast("Any", _Router(bot)), runtime.outbound)

    result = await messenger.send(
        ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID)),
        OutboundMessage((TextPart("hello"),)),
    )

    assert result.failure_kind is DeliveryFailureKind.UNCERTAIN
    assert rollbacks == []


@pytest.mark.asyncio
async def test_onebot_cancel_before_api_send_releases_rate_limit_permit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    second_permit = asyncio.Event()

    class BlockingBot(_Bot):
        async def send_group_msg(self, *, group_id: int, message: Message) -> object:
            entered.set()
            await release.wait()
            return await super().send_group_msg(group_id=group_id, message=message)

    runtime = build_test_runtime(
        outbound_config=OutboundRateLimitConfig(enabled=False),
    )
    permits = (
        OutboundPermit(token=1, group_id=GROUP_ID, reserved_at=0),
        OutboundPermit(token=2, group_id=GROUP_ID, reserved_at=0),
    )
    rollbacks: list[OutboundPermit | None] = []
    next_permit = iter(permits)

    async def acquire_push(
        _group_id: int | None,
        *,
        source: str,
    ) -> OutboundRateLimitDecision:
        assert source == "platform outbound"
        permit = next(next_permit)
        if permit is permits[1]:
            second_permit.set()
        return OutboundRateLimitDecision(allowed=True, permit=permit)

    monkeypatch.setattr(runtime.outbound, "acquire_push", acquire_push)
    monkeypatch.setattr(runtime.outbound, "rollback", rollbacks.append)
    messenger = OneBotOutboundMessenger(
        cast("Any", _Router(BlockingBot())), runtime.outbound
    )
    conversation = ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID))
    message = OutboundMessage((TextPart("hello"),))

    first = asyncio.create_task(messenger.send(conversation, message))
    await entered.wait()
    second = asyncio.create_task(messenger.send(conversation, message))
    await second_permit.wait()
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    release.set()
    assert (await first).delivered
    assert rollbacks == [permits[1]]
