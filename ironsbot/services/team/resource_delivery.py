# SPDX-License-Identifier: MIT
"""Platform-neutral delivery adapter for team-resource subscription notices."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.outbound import MentionPart, OutboundMessage, TextPart
from ironsbot.core.platform import private_conversation_for_actor

if TYPE_CHECKING:
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.team.resource_subscriptions import (
        TeamResourceSubscriptionTarget,
    )


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TeamResourceOutboundSender:
    """Deliver resource notices through typed conversation and mention values."""

    delivery: ProactiveMessageDelivery

    async def send_low_resource_notice(
        self,
        target: TeamResourceSubscriptionTarget,
        message: str,
    ) -> bool:
        conversation = target.conversation
        if conversation is None:
            actor = target.actor
            if actor is None:
                _LOGGER.warning("team resource notice has no recipient")
                return False
            conversation = private_conversation_for_actor(actor)
        parts = (
            *(MentionPart(actor) for actor in target.mention_actors),
            TextPart(message),
        )
        summary = await self.delivery.send(
            OutboundMessage(parts),
            (conversation,),
            action_name="team resource subscription notice",
            interval_seconds=0,
        )
        return bool(summary.succeeded)
