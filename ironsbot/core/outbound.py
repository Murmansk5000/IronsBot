# SPDX-License-Identifier: MIT
"""Platform-neutral outbound message values and delivery port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from ironsbot.core.platform import ActorRef, ConversationRef


class OutboundMessageError(ValueError):
    @classmethod
    def empty_text_part(cls) -> OutboundMessageError:
        return cls("text part must not be empty")

    @classmethod
    def empty_image_content(cls) -> OutboundMessageError:
        return cls("image content must not be empty")

    @classmethod
    def empty_image_content_type(cls) -> OutboundMessageError:
        return cls("image content type must not be empty")

    @classmethod
    def empty_remote_image_url(cls) -> OutboundMessageError:
        return cls("remote image URL must not be empty")

    @classmethod
    def empty_reply_message_id(cls) -> OutboundMessageError:
        return cls("reply message id must not be empty")

    @classmethod
    def empty_message(cls) -> OutboundMessageError:
        return cls("outbound message must contain at least one part")

    @classmethod
    def missing_delivery_message_id(cls) -> OutboundMessageError:
        return cls("incomplete delivery state: missing message id")

    @classmethod
    def missing_delivery_error(cls) -> OutboundMessageError:
        return cls("incomplete delivery state: missing error")


@dataclass(frozen=True, slots=True)
class TextPart:
    text: str

    def __post_init__(self) -> None:
        if not self.text:
            raise OutboundMessageError.empty_text_part()


@dataclass(frozen=True, slots=True)
class BinaryImagePart:
    content: bytes
    content_type: str
    filename: str | None = None

    def __post_init__(self) -> None:
        if not self.content:
            raise OutboundMessageError.empty_image_content()
        if not self.content_type.strip():
            raise OutboundMessageError.empty_image_content_type()


@dataclass(frozen=True, slots=True)
class RemoteImagePart:
    url: str

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise OutboundMessageError.empty_remote_image_url()


@dataclass(frozen=True, slots=True)
class MentionPart:
    actor: ActorRef


MessagePart: TypeAlias = TextPart | BinaryImagePart | RemoteImagePart | MentionPart


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    parts: tuple[MessagePart, ...]

    def __post_init__(self) -> None:
        if not self.parts:
            raise OutboundMessageError.empty_message()


@dataclass(frozen=True, slots=True)
class ReplyContext:
    conversation: ConversationRef
    message_id: str

    def __post_init__(self) -> None:
        if not self.message_id.strip():
            raise OutboundMessageError.empty_reply_message_id()


@dataclass(frozen=True, slots=True)
class DeliveryCapabilities:
    can_reply_to_event: bool
    can_send_proactively: bool
    can_mention_members: bool
    supports_group_context: bool
    supports_private_context: bool
    supports_images: bool


@dataclass(frozen=True, slots=True)
class SendResult:
    delivered: bool
    message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.delivered and not (self.message_id or "").strip():
            raise OutboundMessageError.missing_delivery_message_id()
        if not self.delivered and not (self.error_code or self.error_message):
            raise OutboundMessageError.missing_delivery_error()


class OutboundMessenger(Protocol):
    def capabilities_for(
        self,
        conversation: ConversationRef,
    ) -> DeliveryCapabilities: ...

    def send(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
    ) -> Awaitable[SendResult]: ...

    def reply(
        self,
        context: ReplyContext,
        message: OutboundMessage,
    ) -> Awaitable[SendResult]: ...
