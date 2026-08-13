# SPDX-License-Identifier: MIT
"""Platform-neutral sender for configured message schedules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.outbound import MentionPart, OutboundMessage, TextPart
from ironsbot.services.messaging.proactive_delivery import ProactiveDeliveryRequest

if TYPE_CHECKING:
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.messaging.scheduled_delivery import ScheduledMessageDelivery


@dataclass(frozen=True, slots=True)
class ScheduledMessageOutboundSender:
    """Attach typed group mentions before proactive multi-platform delivery."""

    delivery: ProactiveMessageDelivery

    async def send(self, delivery: ScheduledMessageDelivery) -> None:
        private_message = OutboundMessage((TextPart(delivery.message),))
        group_message = OutboundMessage(
            (
                *(MentionPart(actor) for actor in delivery.group_mentions),
                TextPart(delivery.message),
            )
        )
        await self.delivery.send_many(
            (
                *(
                    ProactiveDeliveryRequest(conversation, private_message)
                    for conversation in delivery.private_conversations
                ),
                *(
                    ProactiveDeliveryRequest(conversation, group_message)
                    for conversation in delivery.group_conversations
                ),
            ),
            action_name=delivery.action_name,
            subscription_key=delivery.subscription_key,
            include_promotions=True,
        )
