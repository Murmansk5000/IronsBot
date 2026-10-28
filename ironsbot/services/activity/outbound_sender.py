# SPDX-License-Identifier: MIT
"""Platform-neutral active sender for activity reminders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import private_conversation_for_actor
from ironsbot.services.messaging.delivery_tasks import DeliveryIntent

if TYPE_CHECKING:
    from ironsbot.services.activity.delivery import ActivityReminderDelivery
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery


@dataclass(frozen=True, slots=True)
class ActivityReminderOutboundSender:
    """Send typed reminder deliveries without requiring a OneBot target type."""

    delivery: ProactiveMessageDelivery

    async def send(self, reminder: ActivityReminderDelivery) -> bool:
        if reminder.message is None:
            return False
        conversations = (
            *reminder.group_conversations,
            *(
                private_conversation_for_actor(actor)
                for actor in reminder.private_actors
            ),
        )
        summary = await self.delivery.send(
            reminder.message,
            conversations,
            action_name=reminder.action_name,
            interval_seconds=0,
            subscription_key="seer_activity_push",
            include_promotions=True,
            intent=DeliveryIntent(
                reminder.business_id,
                reminder.expires_at,
                feature="seer_activity_push",
            )
            if reminder.expires_at is not None
            else None,
        )
        return bool(summary.succeeded)
