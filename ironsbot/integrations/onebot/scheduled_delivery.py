# SPDX-License-Identifier: MIT
"""OneBot adapter for platform-neutral configured message schedules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, ConversationRef, Platform

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.delivery import (
        MessageLimiter,
        OneBotDelivery,
    )
    from ironsbot.services.messaging.scheduled_delivery import (
        ScheduledMessageDelivery,
    )


@dataclass(frozen=True, slots=True)
class OneBotScheduledMessageSender:
    """Translate scheduled delivery references at the OneBot boundary."""

    delivery: OneBotDelivery
    message_limiter: MessageLimiter | None = None

    async def send(self, delivery: ScheduledMessageDelivery) -> None:
        await self.delivery.broadcast(
            delivery.message,
            private_user_ids=_onebot_conversation_ids(
                delivery.private_conversations,
                "private",
            ),
            group_ids=_onebot_conversation_ids(
                delivery.group_conversations,
                "group",
            ),
            group_at_user_ids=_onebot_actor_ids(delivery.group_mentions),
            action_name=delivery.action_name,
            message_limiter=self.message_limiter,
            subscription_key=delivery.subscription_key,
        )


def _onebot_conversation_ids(
    conversations: tuple[ConversationRef, ...],
    kind: str,
) -> tuple[int, ...]:
    return tuple(
        value
        for conversation in conversations
        if conversation.platform is Platform.ONEBOT
        and conversation.kind == kind
        and (value := _positive_int(conversation.id)) is not None
    )


def _onebot_actor_ids(actors: tuple[ActorRef, ...]) -> tuple[int, ...]:
    return tuple(
        value
        for actor in actors
        if actor.platform is Platform.ONEBOT
        and actor.kind == "user"
        and (value := _positive_int(actor.id)) is not None
    )


def _positive_int(value: str) -> int | None:
    return int(value) if value.isdecimal() and int(value) > 0 else None
