# SPDX-License-Identifier: MIT
"""Platform-neutral sender for administrator notices."""

from __future__ import annotations

import logging
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

_LOGGER = logging.getLogger(__name__)


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
        scoped = tuple(actor for actor in private_actors if actor.kind == "member")
        for actor in scoped:
            _LOGGER.warning(
                "%s cannot privately address scoped actor: %s", action_name, actor
            )
        recipients = _notice_recipients(
            tuple(actor for actor in private_actors if actor.kind == "user"),
            group_conversations,
        )
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
            (*scoped, *(recipient_by_conversation[item] for item in summary.failed)),
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
