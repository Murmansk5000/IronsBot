# SPDX-License-Identifier: MIT
"""Platform-neutral inbound identity values.

Adapters convert their native event IDs to these opaque strings at the edge.
Business services must not assume an ID is a QQ number.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime


class Platform(str, Enum):
    ONEBOT = "onebot"
    QQ_OFFICIAL = "qq_official"


ConversationKind = Literal["private", "group", "channel", "guild"]
ActorKind = Literal["user", "member"]
ActorPrincipalKind = Literal[
    "qq",
    "configured_user",
    "official_union",
    "official_endpoint",
]
ConversationPrincipalKind = Literal[
    "qq_group",
    "configured_group",
    "official_group",
    "conversation",
]


def reference_digest(value: str) -> str:
    """Return a stable diagnostic label without exposing a transport ID."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


class PlatformReferenceError(ValueError):
    @classmethod
    def empty_account_id(cls) -> PlatformReferenceError:
        return cls("account id must not be empty")

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
    def unsupported_actor_kind(cls) -> PlatformReferenceError:
        return cls("unsupported actor kind")

    @classmethod
    def missing_member_scope(cls) -> PlatformReferenceError:
        return cls("member actors must include a nonempty scope id")

    @classmethod
    def unexpected_actor_scope(cls) -> PlatformReferenceError:
        return cls("user actors must not include a scope id")

    @classmethod
    def naive_reply_deadline(cls) -> PlatformReferenceError:
        return cls("reply deadline must include a timezone")

    @classmethod
    def unsupported_conversation_kind(cls) -> PlatformReferenceError:
        return cls("unsupported conversation kind")

    @classmethod
    def actor_conversation_platform_mismatch(cls) -> PlatformReferenceError:
        return cls("actor and conversation platforms must match")

    @classmethod
    def actor_conversation_account_mismatch(cls) -> PlatformReferenceError:
        return cls("actor and conversation accounts must match")

    @classmethod
    def mention_conversation_platform_mismatch(cls) -> PlatformReferenceError:
        return cls("direct mention and conversation platforms must match")

    @classmethod
    def mention_conversation_account_mismatch(cls) -> PlatformReferenceError:
        return cls("direct mention and conversation accounts must match")

    @classmethod
    def private_conversation_requires_user_actor(cls) -> PlatformReferenceError:
        return cls("private conversation requires an unscoped user actor")

    @classmethod
    def empty_union_identity(cls) -> PlatformReferenceError:
        return cls("official union identity must contain at least one identifier")

    @classmethod
    def union_identity_requires_official_platform(cls) -> PlatformReferenceError:
        return cls("official union identity requires the QQ Official platform")


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
    kind: ActorKind = "user"
    scope_id: str | None = None
    account_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"user", "member"}:
            raise PlatformReferenceError.unsupported_actor_kind()
        object.__setattr__(
            self,
            "id",
            _required_id(self.id, error=PlatformReferenceError.empty_actor_id),
        )
        if self.account_id is not None:
            object.__setattr__(
                self,
                "account_id",
                _required_id(
                    self.account_id,
                    error=PlatformReferenceError.empty_account_id,
                ),
            )
        if self.scope_id is not None:
            object.__setattr__(
                self,
                "scope_id",
                _required_id(
                    self.scope_id,
                    error=PlatformReferenceError.empty_conversation_id,
                ),
            )
        if self.kind == "member" and self.scope_id is None:
            raise PlatformReferenceError.missing_member_scope()
        if self.kind == "user" and self.scope_id is not None:
            raise PlatformReferenceError.unexpected_actor_scope()


@dataclass(frozen=True, slots=True)
class ConversationRef:
    platform: Platform
    kind: ConversationKind
    id: str
    account_id: str | None = None

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
        if self.account_id is not None:
            object.__setattr__(
                self,
                "account_id",
                _required_id(
                    self.account_id,
                    error=PlatformReferenceError.empty_account_id,
                ),
            )


@dataclass(frozen=True, slots=True)
class OfficialUnionIdentity:
    """Non-addressable cross-application identity evidence from Tencent."""

    union_openid: str | None = None
    union_user_account: str | None = None

    def __post_init__(self) -> None:
        union_openid = (self.union_openid or "").strip() or None
        union_user_account = (self.union_user_account or "").strip() or None
        if union_openid is None and union_user_account is None:
            raise PlatformReferenceError.empty_union_identity()
        object.__setattr__(self, "union_openid", union_openid)
        object.__setattr__(self, "union_user_account", union_user_account)


@dataclass(frozen=True, slots=True)
class ActorPrincipal:
    """Non-addressable owner of user-scoped business state."""

    kind: ActorPrincipalKind
    id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "id",
            _required_id(self.id, error=PlatformReferenceError.empty_actor_id),
        )


@dataclass(frozen=True, slots=True)
class ConversationPrincipal:
    """Non-addressable owner of conversation-scoped business state."""

    kind: ConversationPrincipalKind
    id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "id",
            _required_id(
                self.id,
                error=PlatformReferenceError.empty_conversation_id,
            ),
        )


def private_conversation_for_actor(actor: ActorRef) -> ConversationRef:
    """Build the direct-message conversation owned by one user actor."""

    if actor.kind != "user" or actor.scope_id is not None:
        raise PlatformReferenceError.private_conversation_requires_user_actor()
    return ConversationRef(
        actor.platform,
        "private",
        actor.id,
        account_id=actor.account_id,
    )


def is_supported_message_actor(actor: ActorRef, conversation: ConversationRef) -> bool:
    """Validate group/private identity shape, not actual platform membership."""

    if actor.platform is not conversation.platform:
        return False
    if actor.account_id != conversation.account_id:
        return False
    if conversation.kind == "group":
        return actor.kind == "user" or actor.scope_id == conversation.id
    if conversation.kind == "private":
        return actor.kind == "user" and actor.id == conversation.id
    return False


def validate_reply_deadline(deadline: datetime | None) -> None:
    """Require comparable instants at both sides of the transport boundary."""

    if deadline is not None and (
        deadline.tzinfo is None or deadline.utcoffset() is None
    ):
        raise PlatformReferenceError.naive_reply_deadline()


@dataclass(frozen=True, slots=True)
class IncomingMessageRef:
    """Platform-neutral reference and direct-input facts for one message.

    ``platform`` and ``message_id`` are explicit instead of inferred or named
    generically. This keeps a future official-platform adapter from treating a
    transport message identifier as a OneBot integer by convention.
    """

    platform: Platform
    actor: ActorRef
    conversation: ConversationRef
    message_id: str
    text: str
    direct_mentions: tuple[ActorRef, ...] = ()
    group_role: str | None = None
    reply_to_id: str | None = None
    sequence: str | None = None
    reply_deadline: datetime | None = None
    official_union_identity: OfficialUnionIdentity | None = None
    reply_reference_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "message_id",
            _required_id(
                self.message_id,
                error=PlatformReferenceError.empty_message_id,
            ),
        )
        if (
            self.platform is not self.actor.platform
            or self.platform is not self.conversation.platform
        ):
            raise PlatformReferenceError.actor_conversation_platform_mismatch()
        if self.actor.account_id != self.conversation.account_id:
            raise PlatformReferenceError.actor_conversation_account_mismatch()
        if any(
            mention.platform is not self.platform for mention in self.direct_mentions
        ):
            raise PlatformReferenceError.mention_conversation_platform_mismatch()
        if any(
            mention.account_id != self.conversation.account_id
            for mention in self.direct_mentions
        ):
            raise PlatformReferenceError.mention_conversation_account_mismatch()
        if self.group_role is not None:
            object.__setattr__(self, "group_role", self.group_role.strip() or None)
        if self.reply_to_id is not None:
            object.__setattr__(
                self,
                "reply_to_id",
                _required_id(
                    self.reply_to_id,
                    error=PlatformReferenceError.empty_reply_message_id,
                ),
            )
        if self.sequence is not None:
            object.__setattr__(
                self,
                "sequence",
                _required_id(
                    self.sequence,
                    error=PlatformReferenceError.empty_message_id,
                ),
            )
        validate_reply_deadline(self.reply_deadline)
        if (
            self.official_union_identity is not None
            and self.platform is not Platform.QQ_OFFICIAL
        ):
            raise PlatformReferenceError.union_identity_requires_official_platform()
