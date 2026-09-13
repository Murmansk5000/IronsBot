# SPDX-License-Identifier: MIT
"""Route platform-neutral outbound messages to their owning adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import (
    DeliveryCapabilities,
    DeliveryFailureKind,
    SendResult,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

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


class PlatformOutboundMessenger:
    """Delegate each typed conversation to exactly one platform messenger."""

    def __init__(self, messengers: Mapping[Platform, OutboundMessenger]) -> None:
        self._messengers = dict(messengers)

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
        return await messenger.send(conversation, message)

    async def reply(
        self,
        context: ReplyContext,
        message: OutboundMessage,
    ) -> SendResult:
        messenger = self._messengers.get(context.conversation.platform)
        if messenger is None:
            return _unsupported_result(context.conversation)
        return await messenger.reply(context, message)


def _unsupported_result(conversation: ConversationRef) -> SendResult:
    return SendResult(
        delivered=False,
        error_code="unsupported_platform",
        error_message=f"No outbound messenger for {conversation.platform.value}",
        failure_kind=DeliveryFailureKind.PERMANENT,
    )
