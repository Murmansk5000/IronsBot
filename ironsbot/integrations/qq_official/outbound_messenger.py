# SPDX-License-Identifier: MIT
"""QQ Official implementation of the platform-neutral outbound port."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import nonebot
from nonebot.adapters.qq import Bot as QQOfficialBot
from nonebot.adapters.qq.exception import (
    ActionFailed,
    NetworkError,
    RateLimitException,
    UnauthorizedException,
)

from ironsbot.core.outbound import (
    DeliveryCapabilities,
    DeliveryFailureKind,
    SendResult,
)
from ironsbot.core.platform import Platform
from ironsbot.integrations.qq_official.message_rendering import (
    QQOfficialOutboundMessageError,
    render_qq_official_outbound_message,
)
from ironsbot.integrations.qq_official.reply_sequences import (
    QQOfficialReplySequenceAllocator,
)

if TYPE_CHECKING:
    from nonebot.adapters.qq import Message

    from ironsbot.core.outbound import OutboundMessage, ReplyContext
    from ironsbot.core.platform import ConversationRef


class QQOfficialMessageSender(Protocol):
    async def send_to_c2c(
        self,
        openid: str,
        message: Message,
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> object: ...

    async def send_to_group(
        self,
        group_openid: str,
        message: Message,
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> object: ...


BotProvider = Callable[[str], QQOfficialMessageSender | None]

_SERVER_ERROR_STATUS = 500
_UNSUPPORTED = DeliveryCapabilities(
    can_reply_to_event=False,
    can_send_proactively=False,
    can_mention_members=False,
    supports_group_context=False,
    supports_private_context=False,
    supports_images=False,
)


def _connected_bot(app_id: str) -> QQOfficialBot | None:
    bot = nonebot.get_bots().get(app_id)
    return bot if isinstance(bot, QQOfficialBot) else None


@dataclass(frozen=True, slots=True)
class QQOfficialOutboundMessenger:
    app_id: str
    proactive_enabled: bool = False
    bot_provider: BotProvider = _connected_bot
    reply_sequences: QQOfficialReplySequenceAllocator = field(
        default_factory=QQOfficialReplySequenceAllocator
    )

    def capabilities_for(
        self,
        conversation: ConversationRef,
    ) -> DeliveryCapabilities:
        if not _supports_conversation(conversation):
            return _UNSUPPORTED
        return DeliveryCapabilities(
            can_reply_to_event=True,
            can_send_proactively=self.proactive_enabled,
            can_mention_members=True,
            supports_group_context=True,
            supports_private_context=True,
            supports_images=True,
        )

    async def send(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
    ) -> SendResult:
        if not self.capabilities_for(conversation).can_send_proactively:
            return _failure(
                "proactive_disabled",
                "QQ Official proactive messages are disabled",
                DeliveryFailureKind.PERMANENT,
            )
        return await self._deliver(conversation, message)

    async def reply(
        self,
        context: ReplyContext,
        message: OutboundMessage,
    ) -> SendResult:
        if not self.capabilities_for(context.conversation).can_reply_to_event:
            return _failure(
                "unsupported_conversation",
                "QQ Official supports only group and private conversations",
                DeliveryFailureKind.PERMANENT,
            )
        return await self._deliver(
            context.conversation,
            message,
            message_id=context.message_id,
        )

    async def _deliver(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
        *,
        message_id: str | None = None,
    ) -> SendResult:
        try:
            rendered = render_qq_official_outbound_message(
                message,
                conversation=conversation,
            )
        except QQOfficialOutboundMessageError as error:
            return _failure(
                "unsupported_message",
                str(error),
                DeliveryFailureKind.PERMANENT,
            )
        bot = self.bot_provider(self.app_id)
        if bot is None:
            return _failure(
                "bot_unavailable",
                "No connected QQ Official bot can deliver this message",
                DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
            )
        message_sequence: int | None = None
        if message_id is not None:
            allocation = self.reply_sequences.allocate(message_id)
            if allocation.sequence is None:
                if not self.proactive_enabled:
                    return _failure(
                        f"passive_reply_{allocation.reason}",
                        "QQ Official passive reply window or limit was exhausted",
                        DeliveryFailureKind.PERMANENT,
                    )
                message_id = None
            else:
                message_sequence = allocation.sequence
        try:
            if conversation.kind == "group":
                result = await bot.send_to_group(
                    conversation.id,
                    rendered,
                    msg_id=message_id,
                    msg_seq=message_sequence,
                )
            else:
                result = await bot.send_to_c2c(
                    conversation.id,
                    rendered,
                    msg_id=message_id,
                    msg_seq=message_sequence,
                )
        except Exception as error:  # noqa: BLE001 - transport boundary
            return _exception_result(error)
        result_id = _result_id(result)
        if result_id is None:
            return _failure(
                "missing_message_id",
                "QQ Official send response did not include a message id",
                DeliveryFailureKind.UNCERTAIN,
            )
        return SendResult(delivered=True, message_id=result_id)


def _supports_conversation(conversation: ConversationRef) -> bool:
    return conversation.platform is Platform.QQ_OFFICIAL and conversation.kind in {
        "group",
        "private",
    }


def _result_id(result: object) -> str | None:
    value = getattr(result, "id", None)
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _exception_result(error: Exception) -> SendResult:
    if isinstance(error, RateLimitException):
        kind = DeliveryFailureKind.RETRYABLE
    elif isinstance(error, NetworkError):
        kind = DeliveryFailureKind.UNCERTAIN
    elif isinstance(error, UnauthorizedException):
        kind = DeliveryFailureKind.PERMANENT
    elif isinstance(error, ActionFailed):
        kind = (
            DeliveryFailureKind.RETRYABLE
            if error.status_code >= _SERVER_ERROR_STATUS
            else DeliveryFailureKind.PERMANENT
        )
    else:
        kind = DeliveryFailureKind.RETRYABLE
    return SendResult(
        delivered=False,
        error_code=_error_code(error),
        error_message=str(error),
        trace_id=getattr(error, "trace_id", None),
        failure_kind=kind,
    )


def _error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    return str(code) if code is not None else type(error).__name__


def _failure(
    code: str,
    message: str,
    kind: DeliveryFailureKind,
) -> SendResult:
    return SendResult(
        delivered=False,
        error_code=code,
        error_message=message,
        failure_kind=kind,
    )
