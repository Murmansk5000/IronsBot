# SPDX-License-Identifier: MIT
"""OneBot delivery adapter for platform-neutral activity reminders."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.integrations.onebot.message_rendering import (
    OneBotOutboundMessageError,
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.target_refs import partition_onebot_targets

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.delivery import OneBotDelivery
    from ironsbot.services.activity.delivery import ActivityReminderDelivery
    from ironsbot.services.messaging.delivery import MessageLimiter

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OneBotActivityReminderSender:
    """Preserve legacy OneBot push semantics at the activity delivery edge."""

    delivery: OneBotDelivery
    message_limiter: MessageLimiter

    async def send(self, reminder: ActivityReminderDelivery) -> bool:
        if reminder.message is None:
            return False
        try:
            message = render_onebot_outbound_message(reminder.message)
        except OneBotOutboundMessageError as error:
            _LOGGER.warning("activity reminder cannot render for OneBot: %s", error)
            return False

        targets = partition_onebot_targets(
            private_actors=reminder.private_actors,
            group_conversations=reminder.group_conversations,
        )
        if targets.invalid_actors or targets.invalid_conversations:
            _LOGGER.warning("activity reminder skipped unsupported platform targets")
        result = await self.delivery.broadcast(
            message,
            private_user_ids=targets.private_user_ids,
            group_ids=targets.group_ids,
            action_name=reminder.action_name,
            interval_seconds=1.2,
            message_limiter=self.message_limiter,
            subscription_key="seer_activity_push",
        )
        return bool(result.succeeded)
