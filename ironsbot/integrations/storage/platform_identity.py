# SPDX-License-Identifier: MIT
"""SQLite column values for platform-neutral actor and conversation identities."""

from __future__ import annotations

from dataclasses import dataclass

from ironsbot.core.platform import ActorRef, ConversationRef, Platform


class PlatformIdentityStorageError(ValueError):
    """Raised when persisted identity columns cannot form a core reference."""


@dataclass(frozen=True, slots=True)
class ActorIdentityColumns:
    """The four independent columns that identify a persistent platform actor."""

    platform: str
    kind: str
    actor_id: str
    scope_id: str

    @classmethod
    def from_actor(cls, actor: ActorRef) -> ActorIdentityColumns:
        return cls(
            platform=actor.platform.value,
            kind=actor.kind,
            actor_id=actor.id,
            scope_id=actor.scope_id or "",
        )

    def to_actor(self) -> ActorRef:
        try:
            return ActorRef(
                Platform(self.platform),
                self.actor_id,
                kind=self.kind,  # type: ignore[arg-type]
                scope_id=self.scope_id or None,
            )
        except ValueError as error:
            msg = "invalid stored actor identity"
            raise PlatformIdentityStorageError(msg) from error

    def values(self) -> tuple[str, str, str, str]:
        return (self.platform, self.kind, self.actor_id, self.scope_id)


@dataclass(frozen=True, slots=True)
class ConversationIdentityColumns:
    """The three independent columns that identify a persistent conversation."""

    platform: str
    kind: str
    conversation_id: str

    @classmethod
    def from_conversation(
        cls,
        conversation: ConversationRef,
    ) -> ConversationIdentityColumns:
        return cls(
            platform=conversation.platform.value,
            kind=conversation.kind,
            conversation_id=conversation.id,
        )

    def to_conversation(self) -> ConversationRef:
        try:
            return ConversationRef(
                Platform(self.platform),
                self.kind,  # type: ignore[arg-type]
                self.conversation_id,
            )
        except ValueError as error:
            msg = "invalid stored conversation identity"
            raise PlatformIdentityStorageError(msg) from error

    def values(self) -> tuple[str, str, str]:
        return (self.platform, self.kind, self.conversation_id)
