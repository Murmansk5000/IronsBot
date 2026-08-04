# SPDX-License-Identifier: MIT
"""Platform-neutral inbound identity values.

Adapters convert their native event IDs to these opaque strings at the edge.
Business services must not assume an ID is a QQ number.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable


class Platform(str, Enum):
    ONEBOT = "onebot"
    QQ_OFFICIAL = "qq_official"


ConversationKind = Literal["private", "group", "channel", "guild"]


class PlatformReferenceError(ValueError):
    @classmethod
    def empty_actor_id(cls) -> PlatformReferenceError:
        return cls("actor id must not be empty")

    @classmethod
    def empty_conversation_id(cls) -> PlatformReferenceError:
        return cls("conversation id must not be empty")

    @classmethod
    def empty_message_id(cls) -> PlatformReferenceError:
        return cls("message id must not be empty")

    @classmethod
    def empty_reply_message_id(cls) -> PlatformReferenceError:
        return cls("reply message id must not be empty")

    @classmethod
    def unsupported_conversation_kind(cls) -> PlatformReferenceError:
        return cls("unsupported conversation kind")

    @classmethod
    def actor_conversation_platform_mismatch(cls) -> PlatformReferenceError:
        return cls("actor and conversation platforms must match")

    @classmethod
    def mention_conversation_platform_mismatch(cls) -> PlatformReferenceError:
        return cls("direct mention and conversation platforms must match")


def _required_id(
    value: str,
    *,
    error: Callable[[], PlatformReferenceError],
) -> str:
    normalized = value.strip()
    if not normalized:
        raise error()
    return normalized


@dataclass(frozen=True, slots=True)
class ActorRef:
    platform: Platform
    id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "id",
            _required_id(self.id, error=PlatformReferenceError.empty_actor_id),
        )


@dataclass(frozen=True, slots=True)
class ConversationRef:
    platform: Platform
    kind: ConversationKind
    id: str

    def __post_init__(self) -> None:
        if self.kind not in {"private", "group", "channel", "guild"}:
            raise PlatformReferenceError.unsupported_conversation_kind()
        object.__setattr__(
            self,
            "id",
            _required_id(
                self.id,
                error=PlatformReferenceError.empty_conversation_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class IncomingMessageRef:
    id: str
    actor: ActorRef
    conversation: ConversationRef
    text: str
    direct_mentions: tuple[ActorRef, ...] = ()
    reply_to_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "id",
            _required_id(self.id, error=PlatformReferenceError.empty_message_id),
        )
        if self.actor.platform is not self.conversation.platform:
            raise PlatformReferenceError.actor_conversation_platform_mismatch()
        if any(
            mention.platform is not self.conversation.platform
            for mention in self.direct_mentions
        ):
            raise PlatformReferenceError.mention_conversation_platform_mismatch()
        if self.reply_to_id is not None:
            object.__setattr__(
                self,
                "reply_to_id",
                _required_id(
                    self.reply_to_id,
                    error=PlatformReferenceError.empty_reply_message_id,
                ),
            )
