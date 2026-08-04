# SPDX-License-Identifier: MIT
"""OneBot delivery adapter for platform-neutral administrator notices."""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.outbound import (
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    TextPart,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.messaging.admin_notice import (
    AdminNoticeRecipient,
    AdminNoticeSendSummary,
)

if TYPE_CHECKING:
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
        rendered_message = _render_onebot_message(message)
        if rendered_message is None:
            return AdminNoticeSendSummary(
                (),
                (*private_actors, *group_conversations),
            )

        actors, invalid_actors = _onebot_private_actors(private_actors)
        conversations, invalid_conversations = _onebot_group_conversations(
            group_conversations
        )
        result = await self.delivery.broadcast(
            rendered_message,
            private_user_ids=tuple(int(actor.id) for actor in actors),
            group_ids=tuple(int(conversation.id) for conversation in conversations),
            action_name=action_name,
            interval_seconds=interval_seconds,
            subscription_key=subscription_key,
        )
        succeeded: list[AdminNoticeRecipient] = []
        failed: list[AdminNoticeRecipient] = [
            *invalid_actors,
            *invalid_conversations,
        ]
        actor_by_id = {int(actor.id): actor for actor in actors}
        conversation_by_id = {
            int(conversation.id): conversation for conversation in conversations
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


def _render_onebot_message(message: OutboundMessage) -> Message | None:
    rendered = Message()
    for part in message.parts:
        if isinstance(part, TextPart):
            rendered += MessageSegment.text(part.text)
        elif isinstance(part, BinaryImagePart):
            encoded = b64encode(part.content).decode("ascii")
            rendered += MessageSegment.image(f"base64://{encoded}")
        elif isinstance(part, RemoteImagePart):
            rendered += MessageSegment.image(part.url)
        elif isinstance(part, MentionPart):
            return None
    return rendered


def _onebot_private_actors(
    actors: tuple[ActorRef, ...],
) -> tuple[tuple[ActorRef, ...], tuple[ActorRef, ...]]:
    valid = tuple(actor for actor in actors if _is_onebot_private_actor(actor))
    return valid, tuple(actor for actor in actors if actor not in valid)


def _onebot_group_conversations(
    conversations: tuple[ConversationRef, ...],
) -> tuple[tuple[ConversationRef, ...], tuple[ConversationRef, ...]]:
    valid = tuple(
        conversation
        for conversation in conversations
        if _is_onebot_group_conversation(conversation)
    )
    return valid, tuple(
        conversation for conversation in conversations if conversation not in valid
    )


def _is_onebot_private_actor(actor: ActorRef) -> bool:
    return (
        actor.platform is Platform.ONEBOT
        and actor.kind == "user"
        and actor.id.isdecimal()
        and int(actor.id) > 0
    )


def _is_onebot_group_conversation(conversation: ConversationRef) -> bool:
    return (
        conversation.platform is Platform.ONEBOT
        and conversation.kind == "group"
        and conversation.id.isdecimal()
        and int(conversation.id) > 0
    )


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
