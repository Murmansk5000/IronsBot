# SPDX-License-Identifier: MIT
"""Validation and conversion for core references routed through OneBot v11."""

from __future__ import annotations

from dataclasses import dataclass

from ironsbot.core.platform import ActorRef, ConversationRef, Platform


@dataclass(frozen=True, slots=True)
class OneBotTargetPartition:
    private_actors: tuple[ActorRef, ...]
    group_conversations: tuple[ConversationRef, ...]
    invalid_actors: tuple[ActorRef, ...]
    invalid_conversations: tuple[ConversationRef, ...]

    @property
    def private_user_ids(self) -> tuple[int, ...]:
        return tuple(int(actor.id) for actor in self.private_actors)

    @property
    def group_ids(self) -> tuple[int, ...]:
        return tuple(int(conversation.id) for conversation in self.group_conversations)


def partition_onebot_targets(
    *,
    private_actors: tuple[ActorRef, ...],
    group_conversations: tuple[ConversationRef, ...],
) -> OneBotTargetPartition:
    valid_actors = tuple(
        actor for actor in private_actors if is_onebot_private_actor(actor)
    )
    valid_conversations = tuple(
        conversation
        for conversation in group_conversations
        if is_onebot_group_conversation(conversation)
    )
    return OneBotTargetPartition(
        private_actors=valid_actors,
        group_conversations=valid_conversations,
        invalid_actors=tuple(
            actor for actor in private_actors if actor not in valid_actors
        ),
        invalid_conversations=tuple(
            conversation
            for conversation in group_conversations
            if conversation not in valid_conversations
        ),
    )


def is_onebot_private_actor(actor: ActorRef) -> bool:
    return (
        actor.platform is Platform.ONEBOT
        and actor.kind == "user"
        and actor.id.isdecimal()
        and int(actor.id) > 0
    )


def is_onebot_group_conversation(conversation: ConversationRef) -> bool:
    return (
        conversation.platform is Platform.ONEBOT
        and conversation.kind == "group"
        and conversation.id.isdecimal()
        and int(conversation.id) > 0
    )
