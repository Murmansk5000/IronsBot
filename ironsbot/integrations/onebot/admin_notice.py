# SPDX-License-Identifier: MIT
"""OneBot delivery adapter for platform-neutral administrator notices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.integrations.onebot.message_rendering import (
    OneBotOutboundMessageError,
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.target_refs import partition_onebot_targets
from ironsbot.services.messaging.admin_notice import (
    AdminNoticeRecipient,
    AdminNoticeSendSummary,
)

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.integrations.onebot.delivery import OneBotDelivery


@dataclass(frozen=True, slots=True)
class OneBotAdminNoticeSender:
    """Keep OneBot routing, rate limits and subscription filtering at the edge."""

    delivery: OneBotDelivery

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
        try:
            rendered_message = render_onebot_outbound_message(message)
        except OneBotOutboundMessageError:
            return AdminNoticeSendSummary(
                (),
                (*private_actors, *group_conversations),
            )

        targets = partition_onebot_targets(
            private_actors=private_actors,
            group_conversations=group_conversations,
        )
        result = await self.delivery.broadcast(
            rendered_message,
            private_user_ids=targets.private_user_ids,
            group_ids=targets.group_ids,
            action_name=action_name,
            interval_seconds=interval_seconds,
            subscription_key=subscription_key,
        )
        succeeded: list[AdminNoticeRecipient] = []
        failed: list[AdminNoticeRecipient] = [
            *targets.invalid_actors,
            *targets.invalid_conversations,
        ]
        actor_by_id = {int(actor.id): actor for actor in targets.private_actors}
        conversation_by_id = {
            int(conversation.id): conversation
            for conversation in targets.group_conversations
        }
        for target in result.succeeded:
            recipient = _recipient_for_target(
                target.target_type,
                target.target_id,
                actor_by_id,
                conversation_by_id,
            )
            if recipient is not None:
                succeeded.append(recipient)
        for target in result.failed:
            recipient = _recipient_for_target(
                target.target_type,
                target.target_id,
                actor_by_id,
                conversation_by_id,
            )
            if recipient is not None:
                failed.append(recipient)
        return AdminNoticeSendSummary(tuple(succeeded), tuple(failed))


def _recipient_for_target(
    target_type: str,
    target_id: int,
    actor_by_id: dict[int, ActorRef],
    conversation_by_id: dict[int, ConversationRef],
) -> AdminNoticeRecipient | None:
    if target_type == "private":
        return actor_by_id.get(target_id)
    if target_type == "group":
        return conversation_by_id.get(target_id)
    return None
