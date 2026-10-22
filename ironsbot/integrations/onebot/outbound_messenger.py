# SPDX-License-Identifier: MIT
"""OneBot v11 implementation of the platform-neutral outbound port."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from time import monotonic
from typing import TYPE_CHECKING

from ironsbot.core.outbound import (
    COMMAND_REPLY_TEMPLATE,
    DeliveryCapabilities,
    DeliveryFailureKind,
    DeliveryHistoryStatus,
    ExecutionIdentity,
    OutboundMessage,
    ReplyContext,
    SendResult,
)
from ironsbot.core.platform import (
    ConversationRef,
    Platform,
    is_supported_message_actor,
    reference_digest,
)
from ironsbot.integrations.onebot.execution_identity import (
    OneBotExecutionIdentityResolver,
)
from ironsbot.integrations.onebot.message_rendering import (
    OneBotOutboundMessageError,
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.message_segments import onebot_own_account_input
from ironsbot.integrations.onebot.receipts import (
    onebot_result_message_id,
    onebot_send_failure,
    onebot_send_result,
)

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ActorRef
    from ironsbot.integrations.onebot.connections import OneBotConnection
    from ironsbot.integrations.onebot.message_segments import OneBotMessage
    from ironsbot.integrations.onebot.router import BotRouter
    from ironsbot.services.messaging.outbound_limits import (
        GroupOutboundRateLimitService,
        OutboundSendAttempt,
    )
    from ironsbot.services.own_commands import OwnAccountCommandPolicy, OwnAccountEcho


logger = logging.getLogger(__name__)

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
_HISTORY_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class _ReplySource:
    bot: OneBotConnection
    identity: ExecutionIdentity
    actor: ActorRef


class OneBotOutboundMessenger:
    """Translate core outbound values only after routing to a OneBot bot."""

    def __init__(
        self,
        router: BotRouter,
        outbound: GroupOutboundRateLimitService,
        *,
        enabled: bool = True,
        self_commands: OwnAccountCommandPolicy | None = None,
        transport_failure_cooldown_seconds: float = 60.0,
    ) -> None:
        self._router = router
        self._outbound = outbound
        self._enabled = enabled
        self._self_commands = self_commands
        self.identity_resolver = OneBotExecutionIdentityResolver(
            router.connections, router.policy.account_name
        )
        self._push_locks: dict[str, asyncio.Lock] = {}
        self._transport_unavailable_until: dict[str, float] = {}
        self._transport_failure_cooldown_seconds = max(
            0.0, transport_failure_cooldown_seconds
        )

    def capabilities_for(
        self,
        conversation: ConversationRef,
    ) -> DeliveryCapabilities:
        return (
            _ONEBOT_CAPABILITIES
            if self._enabled
            and _supports_conversation(conversation)
            and self._router.policy.allows_outbound(conversation)
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

    async def reply_from(
        self,
        bot: OneBotConnection,
        incoming: MessageInputContext,
        message: OutboundMessage,
    ) -> SendResult:
        identity = incoming.execution_identity
        if (
            identity is None
            or identity.platform is not Platform.ONEBOT
            or incoming.message.platform is not Platform.ONEBOT
            or incoming.message.actor.platform is not Platform.ONEBOT
            or incoming.message.conversation.platform is not Platform.ONEBOT
            or identity.account_id != str(bot.self_id)
        ):
            return SendResult(
                delivered=False,
                attempted=False,
                error_code="account_mismatch",
                failure_kind=DeliveryFailureKind.PERMANENT,
            )
        template = (
            replace(COMMAND_REPLY_TEMPLATE, mention_sender=False)
            if incoming.message.actor.id == identity.account_id
            else COMMAND_REPLY_TEMPLATE
        )
        prepared = template.prepare(incoming.message, message)
        return await self._deliver(
            incoming.message.conversation,
            prepared.message,
            reply_to_id=prepared.context.message_id if prepared.context else None,
            proactive=False,
            source=_ReplySource(bot, identity, incoming.message.actor),
        )

    async def send_from(
        self,
        bot: OneBotConnection,
        context: CommandContext,
        message: OutboundMessage,
    ) -> SendResult:
        """Send a normalized notice response on its receiving connection."""

        if (
            context.actor.platform is not Platform.ONEBOT
            or context.conversation.platform is not Platform.ONEBOT
            or not is_supported_message_actor(context.actor, context.conversation)
            or any(
                account is not None and account != str(bot.self_id)
                for account in (
                    context.actor.account_id,
                    context.conversation.account_id,
                )
            )
        ):
            return SendResult(
                delivered=False,
                attempted=False,
                error_code="account_mismatch",
                failure_kind=DeliveryFailureKind.PERMANENT,
            )
        return await self._deliver(
            context.conversation,
            message,
            proactive=False,
            source=_ReplySource(
                bot, ExecutionIdentity(Platform.ONEBOT, str(bot.self_id)), context.actor
            ),
        )

    async def verify_history(
        self,
        conversation: ConversationRef,
        receipt: SendResult,
    ) -> DeliveryHistoryStatus:
        message_id = onebot_result_message_id(receipt)
        if (
            conversation.platform is not Platform.ONEBOT
            or not receipt.delivered
            or receipt.execution_identity is None
            or receipt.execution_identity.platform is not Platform.ONEBOT
            or message_id is None
        ):
            return DeliveryHistoryStatus.UNSUPPORTED
        bot = self._router.for_conversation(conversation)
        if bot is None or str(bot.self_id) != receipt.execution_identity.account_id:
            return DeliveryHistoryStatus.UNSUPPORTED
        try:
            result = await asyncio.wait_for(
                bot.call_api("get_msg", message_id=int(message_id)),
                timeout=_HISTORY_TIMEOUT_SECONDS,
            )
        except Exception as error:  # noqa: BLE001 - optional history lookup
            logger.warning(
                "OneBot history verification failed: error_type=%s",
                type(error).__name__,
            )
            return DeliveryHistoryStatus.ERROR
        return (
            DeliveryHistoryStatus.CONFIRMED
            if onebot_result_message_id(result) == message_id
            else DeliveryHistoryStatus.MISSING
        )

    async def _deliver(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
        *,
        reply_to_id: str | None = None,
        proactive: bool,
        source: _ReplySource | None = None,
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
            source=source,
        )

    async def _send_rendered(
        self,
        conversation: ConversationRef,
        rendered: OneBotMessage,
        *,
        proactive: bool,
        source: _ReplySource | None,
    ) -> SendResult:
        bot = (
            source.bot
            if source is not None
            else self._router.for_conversation(conversation)
        )
        if bot is None:
            return SendResult(
                delivered=False,
                error_code="bot_unavailable",
                attempted=False,
                error_message="No connected OneBot bot can deliver this message",
                failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
            )
        identity = (
            source.identity
            if source is not None
            else await self.identity_resolver.resolve(
                ExecutionIdentity(Platform.ONEBOT, str(bot.self_id))
            )
        )
        assert identity is not None
        account_key = identity.account_id

        async def send(attempt: OutboundSendAttempt) -> SendResult:
            if proactive:
                lock = self._push_locks.setdefault(account_key, asyncio.Lock())
                async with lock:
                    return await self._send_to_bot(
                        bot,
                        conversation,
                        rendered,
                        identity=identity,
                        attempt=attempt,
                        account_key=account_key,
                        proactive=True,
                    )
            return await self._send_to_bot(
                bot,
                conversation,
                rendered,
                identity=identity,
                attempt=attempt,
                account_key=account_key,
                proactive=False,
            )

        result = await self._outbound.execute_send(
            _group_id(conversation),
            send,
            proactive=proactive,
            actor=source.actor if source is not None else None,
        )
        return (
            result
            if result.execution_identity is not None
            else replace(result, execution_identity=identity)
        )

    async def _send_to_bot(  # noqa: PLR0913
        self,
        bot: OneBotConnection,
        conversation: ConversationRef,
        rendered: OneBotMessage,
        *,
        identity: ExecutionIdentity,
        attempt: OutboundSendAttempt,
        account_key: str,
        proactive: bool,
    ) -> SendResult:
        probing = proactive and account_key in self._transport_unavailable_until
        if (
            proactive
            and self._transport_unavailable_until.get(account_key, 0) > monotonic()
        ):
            return SendResult(
                delivered=False,
                error_code="transport_circuit_open",
                attempted=False,
                failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
                execution_identity=identity,
            )
        echo: OwnAccountEcho | None = None
        receipt: SendResult | None = None
        try:
            message = (
                [
                    *rendered,
                    {
                        "type": "text",
                        "data": {"text": f"\n\n{attempt.cooldown_notice}"},
                    },
                ]
                if attempt.cooldown_notice
                else rendered
            )
            if self._self_commands is not None:
                outgoing = onebot_own_account_input(
                    identity.account_id, conversation, message, is_own_message=True
                )
                if outgoing is not None:
                    echo = self._self_commands.begin_outbound(outgoing)
            attempt.start()
            result = await _send_onebot_message(bot, conversation, message)
            receipt = onebot_send_result(result, execution_identity=identity)
        except Exception as error:  # noqa: BLE001 - delivery boundary
            failure = onebot_send_failure(error, execution_identity=identity)
            receipt = failure.result
            kind = failure.result.failure_kind
            attempt.interrupted = failure.interrupted or probing
            logger.warning(
                "OneBot outbound delivery failed: kind=%s ref=%s error_type=%s",
                conversation.kind,
                reference_digest(conversation.id),
                type(error).__name__,
            )
            if (
                kind is DeliveryFailureKind.TRANSPORT_UNAVAILABLE
                or failure.interrupted
                or probing
            ) and self._transport_failure_cooldown_seconds > 0:
                self._transport_unavailable_until[account_key] = (
                    monotonic() + self._transport_failure_cooldown_seconds
                )
            return receipt
        finally:
            if self._self_commands is not None:
                self._self_commands.finish_outbound(echo, receipt)
        assert receipt is not None
        if not receipt.delivered:
            if probing and self._transport_failure_cooldown_seconds > 0:
                attempt.interrupted = True
                self._transport_unavailable_until[account_key] = (
                    monotonic() + self._transport_failure_cooldown_seconds
                )
        else:
            self._transport_unavailable_until.pop(account_key, None)
        return receipt


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
    bot: OneBotConnection,
    conversation: ConversationRef,
    message: OneBotMessage,
) -> object:
    target_id = int(conversation.id)
    if conversation.kind == "private":
        return await bot.call_api(
            "send_private_msg", user_id=target_id, message=message
        )
    return await bot.call_api("send_group_msg", group_id=target_id, message=message)
