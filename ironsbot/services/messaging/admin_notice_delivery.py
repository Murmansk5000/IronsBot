# SPDX-License-Identifier: MIT
"""Platform-neutral sender for administrator notices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import private_conversation_for_actor
from ironsbot.services.messaging.admin_notice import (
    AdminNoticeRecipient,
    AdminNoticeSendSummary,
)

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery


@dataclass(frozen=True, slots=True)
class OutboundAdminNoticeSender:
    """Deliver notices through the configured platform-neutral push service."""

    delivery: ProactiveMessageDelivery

    async def send_admin_notice(  # noqa: PLR0913
        self,
        message: OutboundMessage,
        *,
        private_actors: tuple[ActorRef, ...],
        group_conversations: tuple[ConversationRef, ...],
        subscription_key: str,
        action_name: str,
        interval_seconds: float,
    ) -> AdminNoticeSendSummary:
        recipients = _notice_recipients(private_actors, group_conversations)
        summary = await self.delivery.send(
            message,
            (conversation for conversation, _recipient in recipients),
            action_name=action_name,
            interval_seconds=interval_seconds,
            subscription_key=subscription_key,
        )
        recipient_by_conversation = dict(recipients)
        return AdminNoticeSendSummary(
            tuple(
                recipient_by_conversation[conversation]
                for conversation in summary.succeeded
            ),
            tuple(
                recipient_by_conversation[conversation]
                for conversation in summary.failed
            ),
        )


def _notice_recipients(
    private_actors: tuple[ActorRef, ...],
    group_conversations: tuple[ConversationRef, ...],
) -> tuple[tuple[ConversationRef, AdminNoticeRecipient], ...]:
    return tuple(
        (
            private_conversation_for_actor(actor),
            actor,
        )
        for actor in private_actors
    ) + tuple((conversation, conversation) for conversation in group_conversations)
