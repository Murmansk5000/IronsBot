# SPDX-License-Identifier: MIT
"""OneBot v11 implementation of the platform-neutral outbound port."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import TYPE_CHECKING, Any, Protocol

from nonebot.log import logger

from ironsbot.core.outbound import (
    DeliveryCapabilities,
    DeliveryFailureKind,
    ExecutionIdentity,
    OutboundMessage,
    ReplyContext,
    SendResult,
)
from ironsbot.core.platform import ConversationRef, Platform, reference_digest
from ironsbot.integrations.onebot.message_rendering import (
    OneBotOutboundMessageError,
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.outbound import (
    GroupOutboundRateLimitService,
    OutboundRateLimitDecision,
    use_preacquired_push_permit,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Message

    from ironsbot.integrations.onebot.router import BotRouter


_ONEBOT_CAPABILITIES = DeliveryCapabilities(
    can_reply_to_event=True,
    can_send_proactively=True,
    can_mention_members=True,
    supports_group_context=True,
    supports_private_context=True,
    supports_images=True,
)
_UNSUPPORTED_CAPABILITIES = DeliveryCapabilities(
    can_reply_to_event=False,
    can_send_proactively=False,
    can_mention_members=False,
    supports_group_context=False,
    supports_private_context=False,
    supports_images=False,
)


class OneBotMessageSender(Protocol):
    """Minimal OneBot send API required by the platform outbound adapter."""

    async def send_private_msg(self, *, user_id: int, message: Message) -> object: ...

    async def send_group_msg(self, *, group_id: int, message: Message) -> object: ...


class OneBotOutboundMessenger:
    """Translate core outbound values only after routing to a OneBot bot."""

    def __init__(
        self,
        router: BotRouter,
        outbound: GroupOutboundRateLimitService,
        *,
        enabled: bool = True,
        transport_failure_cooldown_seconds: float = 60.0,
    ) -> None:
        self._router = router
        self._outbound = outbound
        self._enabled = enabled
        self._identities: dict[str, ExecutionIdentity] = {}
        self._push_locks: dict[str, asyncio.Lock] = {}
        self._transport_unavailable_until: dict[str, float] = {}
        self._transport_failure_cooldown_seconds = max(
            0.0, transport_failure_cooldown_seconds
        )

    async def _identity(self, bot: Any) -> ExecutionIdentity:
        account_id = str(getattr(bot, "self_id", "")).strip()
        if account_id in self._identities:
            return self._identities[account_id]
        nickname = ""
        try:
            response = await asyncio.wait_for(bot.get_login_info(), timeout=2)
            if isinstance(response, dict):
                nickname = str(response.get("nickname") or "").strip()
        except Exception:  # noqa: BLE001 - nickname lookup must not block delivery
            pass
        if not nickname:
            config = getattr(self._router, "config", None)
            aliases = getattr(config, "bot_aliases", {})
            nickname = next(
                (name for name, value in aliases.items() if str(value) == account_id),
                account_id,
            )
        identity = ExecutionIdentity(Platform.ONEBOT, account_id, nickname)
        if account_id:
            self._identities[account_id] = identity
        return identity

    def capabilities_for(
        self,
        conversation: ConversationRef,
    ) -> DeliveryCapabilities:
        return (
            _ONEBOT_CAPABILITIES
            if self._enabled
            and _supports_conversation(conversation)
            and self._router.allows_outbound(conversation)
            else _UNSUPPORTED_CAPABILITIES
        )

    async def send(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
    ) -> SendResult:
        return await self._deliver(conversation, message, proactive=True)

    async def reply(
        self,
        context: ReplyContext,
        message: OutboundMessage,
    ) -> SendResult:
        return await self._deliver(
            context.conversation,
            message,
            reply_to_id=context.message_id,
            proactive=False,
        )

    async def _deliver(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
        *,
        reply_to_id: str | None = None,
        proactive: bool,
    ) -> SendResult:
        if not self._enabled:
            return SendResult(
                delivered=False,
                error_code="outbound_disabled",
                attempted=False,
                error_message="OneBot outbound messaging is disabled",
                failure_kind=DeliveryFailureKind.PERMANENT,
            )
        if not _supports_conversation(conversation):
            return SendResult(
                delivered=False,
                error_code="unsupported_conversation",
                attempted=False,
                error_message=("OneBot only supports private and group conversations"),
                failure_kind=DeliveryFailureKind.PERMANENT,
            )
        try:
            rendered = render_onebot_outbound_message(
                message,
                conversation=conversation,
                reply_to_id=reply_to_id,
            )
        except OneBotOutboundMessageError as error:
            return SendResult(
                delivered=False,
                error_code="unsupported_message",
                attempted=False,
                error_message=str(error),
                failure_kind=DeliveryFailureKind.PERMANENT,
            )
        return await self._send_rendered(
            conversation,
            rendered,
            proactive=proactive,
        )

    async def _send_rendered(
        self,
        conversation: ConversationRef,
        rendered: Message,
        *,
        proactive: bool,
    ) -> SendResult:
        bot = self._router.for_conversation(conversation)
        if bot is None:
            return SendResult(
                delivered=False,
                error_code="bot_unavailable",
                attempted=False,
                error_message="No connected OneBot bot can deliver this message",
                failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
            )
        identity = await self._identity(bot)
        account_key = str(getattr(bot, "self_id", "") or id(bot))
        decision = (
            await self._outbound.acquire_push(
                _group_id(conversation),
                source="platform outbound",
            )
            if proactive
            else None
        )
        if decision is not None and not decision.allowed:
            return SendResult(
                delivered=False,
                error_code=decision.reason or "rate_limit",
                attempted=False,
                error_message="Outbound group message is rate limited",
                failure_kind=DeliveryFailureKind.RETRYABLE,
                execution_identity=identity,
            )
        if proactive:
            lock = self._push_locks.setdefault(account_key, asyncio.Lock())
            try:
                await lock.acquire()
            except asyncio.CancelledError:
                if decision is not None:
                    self._outbound.rollback(decision.permit)
                raise
            try:
                return await self._send_to_bot(
                    bot,
                    conversation,
                    rendered,
                    identity=identity,
                    decision=decision,
                    account_key=account_key,
                    proactive=True,
                )
            finally:
                lock.release()
        return await self._send_to_bot(
            bot,
            conversation,
            rendered,
            identity=identity,
            decision=decision,
            account_key=account_key,
            proactive=False,
        )

    async def _send_to_bot(  # noqa: PLR0913
        self,
        bot: Any,
        conversation: ConversationRef,
        rendered: Message,
        *,
        identity: ExecutionIdentity,
        decision: OutboundRateLimitDecision | None,
        account_key: str,
        proactive: bool,
    ) -> SendResult:
        if (
            proactive
            and self._transport_unavailable_until.get(account_key, 0) > monotonic()
        ):
            if decision is not None:
                self._outbound.rollback(decision.permit)
            return SendResult(
                delivered=False,
                error_code="transport_circuit_open",
                attempted=False,
                failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
                execution_identity=identity,
            )
        try:
            with use_preacquired_push_permit(
                self._outbound,
                decision.permit if decision is not None else None,
            ):
                result = await _send_onebot_message(bot, conversation, rendered)
        except Exception as error:  # noqa: BLE001 - delivery boundary
            kind = _onebot_failure_kind(error)
            if decision is not None and kind is not DeliveryFailureKind.UNCERTAIN:
                self._outbound.rollback(decision.permit)
            logger.warning(
                "OneBot outbound delivery failed: kind={} ref={} error_type={}",
                conversation.kind,
                reference_digest(conversation.id),
                type(error).__name__,
            )
            if kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE:
                if self._transport_failure_cooldown_seconds > 0:
                    self._transport_unavailable_until[account_key] = (
                        monotonic() + self._transport_failure_cooldown_seconds
                    )
                if proactive and conversation.kind == "group":
                    self._outbound.discard_pending_pushes(int(conversation.id))
            return SendResult(
                delivered=False,
                error_code="delivery_failed",
                error_message=type(error).__name__,
                failure_kind=kind,
                execution_identity=identity,
            )
        self._transport_unavailable_until.pop(account_key, None)
        message_id = onebot_result_message_id(result)
        if message_id is None:
            return SendResult(
                delivered=False,
                error_code="missing_message_id",
                error_message="OneBot send response did not include message_id",
                failure_kind=DeliveryFailureKind.UNCERTAIN,
                execution_identity=identity,
            )
        return SendResult(
            delivered=True, message_id=message_id, execution_identity=identity
        )


def _supports_conversation(conversation: ConversationRef) -> bool:
    return (
        conversation.platform is Platform.ONEBOT
        and conversation.kind in {"private", "group"}
        and conversation.id.isdecimal()
        and int(conversation.id) > 0
    )


def _group_id(conversation: ConversationRef) -> int | None:
    return int(conversation.id) if conversation.kind == "group" else None


async def _send_onebot_message(
    bot: OneBotMessageSender,
    conversation: ConversationRef,
    message: Message,
) -> object:
    target_id = int(conversation.id)
    if conversation.kind == "private":
        return await bot.send_private_msg(user_id=target_id, message=message)
    return await bot.send_group_msg(group_id=target_id, message=message)


def onebot_result_message_id(result: object) -> str | None:
    if isinstance(result, dict):
        value: Any = result.get("message_id")
    else:
        value = getattr(result, "message_id", None)
    text = str(value).strip() if value is not None else ""
    return text or None


def _onebot_failure_kind(error: Exception) -> DeliveryFailureKind:
    """Classify OneBot-specific failures at the adapter boundary."""

    text = " ".join((type(error).__name__, str(error), repr(error))).casefold()
    if any(
        marker in text
        for marker in (
            "1006514",
            "网络连接异常",
            "账号状态为离线",
            "账号已离线",
            "not connected",
            "connection closed",
            "connection reset",
            "websocket is closed",
        )
    ):
        return DeliveryFailureKind.TRANSPORT_UNAVAILABLE
    return DeliveryFailureKind.UNCERTAIN
