# SPDX-License-Identifier: MIT
"""Route platform-neutral outbound messages to their owning adapter."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from ironsbot.core.outbound import (
    DeliveryCapabilities,
    DeliveryFailureKind,
    SendResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ironsbot.core.outbound import OutboundMessage, OutboundMessenger, ReplyContext
    from ironsbot.core.platform import ConversationRef, Platform


_UNSUPPORTED = DeliveryCapabilities(
    can_reply_to_event=False,
    can_send_proactively=False,
    can_mention_members=False,
    supports_group_context=False,
    supports_private_context=False,
    supports_images=False,
)
logger = logging.getLogger(__name__)


class PlatformOutboundMessenger:
    """Delegate each typed conversation to exactly one platform messenger."""

    def __init__(self, messengers: Mapping[Platform, OutboundMessenger]) -> None:
        self._messengers = dict(messengers)
        self.on_available: Callable[[ConversationRef], None] | None = None

    def capabilities_for(
        self,
        conversation: ConversationRef,
    ) -> DeliveryCapabilities:
        messenger = self._messengers.get(conversation.platform)
        return (
            _UNSUPPORTED
            if messenger is None
            else messenger.capabilities_for(conversation)
        )

    async def send(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
    ) -> SendResult:
        messenger = self._messengers.get(conversation.platform)
        if messenger is None:
            return _unsupported_result(conversation)
        result = await messenger.send(conversation, message)
        self._available(conversation, result)
        return result

    async def reply(
        self,
        context: ReplyContext,
        message: OutboundMessage,
    ) -> SendResult:
        messenger = self._messengers.get(context.conversation.platform)
        if messenger is None:
            return _unsupported_result(context.conversation)
        result = await messenger.reply(context, message)
        self._available(context.conversation, result)
        return result

    def _available(self, target: ConversationRef, result: SendResult) -> None:
        if not result.delivered or self.on_available is None:
            return
        actual = (
            replace(target, account_id=result.execution_identity.account_id)
            if result.execution_identity
            else target
        )
        try:
            self.on_available(actual)
        except Exception:
            logger.exception("delivery recovery wake failed after accepted message")


def _unsupported_result(conversation: ConversationRef) -> SendResult:
    return SendResult(
        delivered=False,
        error_code="unsupported_platform",
        error_message=f"No outbound messenger for {conversation.platform.value}",
        failure_kind=DeliveryFailureKind.PERMANENT,
    )
