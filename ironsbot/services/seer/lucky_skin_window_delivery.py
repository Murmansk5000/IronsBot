# SPDX-License-Identifier: MIT
"""Platform-neutral delivery adapter for lucky-skin-window notices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import private_conversation_for_actor
from ironsbot.services.seer.lucky_skin_window import (
    LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
)

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.messaging.subscriptions import PushSubscriptionRepository


@dataclass(frozen=True, slots=True)
class LuckySkinWindowOutboundSender:
    """Deliver one configured account's daily result through an outbound port."""

    delivery: ProactiveMessageDelivery
    subscriptions: PushSubscriptionRepository

    async def send_daily_notice(
        self,
        actor: ActorRef,
        message: str,
        *,
        day: str,
    ) -> bool:
        conversation = private_conversation_for_actor(actor)
        if self.subscriptions.is_unsubscribed(
            conversation,
            LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
        ):
            return False
        if not self.subscriptions.mark_daily_hint_sent(
            conversation,
            "lucky_skin_window_delivery",
            today=day,
        ):
            return False
        summary = await self.delivery.send(
            OutboundMessage((TextPart(message),)),
            (conversation,),
            action_name="lucky skin window daily notice",
            interval_seconds=0,
            subscription_key=LUCKY_SKIN_WINDOW_SUBSCRIPTION_KEY,
        )
        return bool(summary.succeeded)
