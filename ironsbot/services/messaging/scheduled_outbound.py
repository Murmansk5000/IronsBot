# SPDX-License-Identifier: MIT
"""Platform-neutral sender for configured message schedules."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.outbound import MentionPart, OutboundMessage, TextPart
from ironsbot.core.platform import Platform, reference_digest
from ironsbot.services.messaging.proactive_delivery import ProactiveDeliveryRequest

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
    from ironsbot.services.messaging.scheduled_delivery import ScheduledMessageDelivery


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScheduledMessageOutboundSender:
    """Attach typed group mentions before proactive multi-platform delivery."""

    delivery: ProactiveMessageDelivery
    official_member_for_qq: Callable[[str, ConversationRef], ActorRef | None] | None = (
        None
    )

    async def send(self, delivery: ScheduledMessageDelivery) -> None:  # noqa: C901
        sequences: dict[ConversationRef, list[OutboundMessage]] = {}
        for message in delivery.messages:
            seen: set[ConversationRef] = set()
            requests = [
                ProactiveDeliveryRequest(
                    conversation, OutboundMessage.from_text(message)
                )
                for conversation in delivery.private_conversations
            ]
            for conversation in delivery.group_conversations:
                mentions = self._mentions_for(conversation, delivery.group_mentions)
                if mentions is None:
                    logger.warning(
                        "Scheduled text unresolved group mentions: "
                        "platform=%s account=%s group=%s action=%s",
                        conversation.platform.value,
                        conversation.account_id,
                        reference_digest(conversation.id),
                        delivery.action_name,
                    )
                    if not delivery.unresolved_mentions_as_text:
                        continue
                    message_text = (
                        f"{delivery.mention_fallback_name}，{message}"
                        if delivery.mention_fallback_name
                        else message
                    )
                    mentions = ()
                else:
                    message_text = message
                requests.append(
                    ProactiveDeliveryRequest(
                        conversation,
                        OutboundMessage(
                            (
                                *[MentionPart(actor) for actor in mentions],
                                TextPart(message_text),
                            )
                        ),
                    )
                )
            for request in requests:
                routes = self.delivery.private_routes
                target = (
                    routes.selected_for(request.conversation)
                    if routes is not None
                    else request.conversation
                ) or request.conversation
                if target not in seen:
                    sequences.setdefault(target, []).append(request.message)
                    seen.add(target)

        async def send_sequence(
            conversation: ConversationRef, messages: list[OutboundMessage]
        ) -> None:
            for message in messages:
                await self.delivery.send(
                    message,
                    (conversation,),
                    action_name=delivery.action_name,
                    subscription_key=delivery.subscription_key,
                    include_promotions=True,
                )

        limit = self.delivery.policy.max_parallel_targets
        semaphore = asyncio.Semaphore(limit) if limit > 0 else None

        async def run_sequence(
            conversation: ConversationRef, messages: list[OutboundMessage]
        ) -> None:
            if semaphore is None:
                await send_sequence(conversation, messages)
            else:
                async with semaphore:
                    await send_sequence(conversation, messages)

        await asyncio.gather(
            *(run_sequence(target, messages) for target, messages in sequences.items())
        )

    def _mentions_for(
        self,
        conversation: ConversationRef,
        mentions: tuple[ActorRef, ...],
    ) -> tuple[ActorRef, ...] | None:
        if conversation.platform is Platform.ONEBOT:
            return mentions
        if self.official_member_for_qq is None:
            return None if mentions else ()
        resolved = tuple(
            self.official_member_for_qq(actor.id, conversation) for actor in mentions
        )
        if any(actor is None for actor in resolved):
            return None
        return tuple(actor for actor in resolved if actor is not None)
