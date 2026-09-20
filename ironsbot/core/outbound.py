# SPDX-License-Identifier: MIT
"""Platform-neutral outbound message values and delivery port."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from string import Formatter
from typing import TYPE_CHECKING, Protocol, TypeAlias

from ironsbot.core.platform import validate_reply_deadline

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from datetime import datetime

    from ironsbot.core.interactive_prompts import PromptSession
    from ironsbot.core.platform import ActorRef, ConversationRef, IncomingMessageRef


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
    def empty_reply_sequence(cls) -> OutboundMessageError:
        return cls("reply sequence must not be empty")

    @classmethod
    def empty_message(cls) -> OutboundMessageError:
        return cls("outbound message must contain at least one part")

    @classmethod
    def missing_delivery_message_id(cls) -> OutboundMessageError:
        return cls("incomplete delivery state: missing message id")

    @classmethod
    def missing_delivery_error(cls) -> OutboundMessageError:
        return cls("incomplete delivery state: missing error")

    @classmethod
    def successful_delivery_failure_kind(cls) -> OutboundMessageError:
        return cls("successful delivery must not have a failure kind")


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
    prompt: PromptSession | None = None

    def __post_init__(self) -> None:
        if not self.parts:
            raise OutboundMessageError.empty_message()

    @classmethod
    def from_text(cls, text: str) -> OutboundMessage:
        """Build the canonical one-part text message."""

        return cls((TextPart(text),))


def address_message_to(
    message: OutboundMessage,
    actors: tuple[ActorRef, ...],
) -> OutboundMessage:
    """Address a message to explicit member targets, preserving their order."""

    targets = tuple(dict.fromkeys(actors))
    if not targets:
        return message
    prefix: list[MessagePart] = []
    for actor in targets:
        prefix.extend((MentionPart(actor), TextPart(" ")))
    return OutboundMessage((*prefix, *message.parts), prompt=message.prompt)


def format_outbound_message(
    template: str,
    /,
    **values: object,
) -> OutboundMessage:
    """Format text fields while preserving structured outbound message parts."""

    formatter = Formatter()
    parts: list[MessagePart] = []
    for literal, field_name, format_spec, conversion in formatter.parse(template):
        _append_text_part(parts, literal)
        if field_name is None:
            continue
        if field_name not in values:
            raise KeyError(field_name)
        value = values[field_name]
        if isinstance(value, (TextPart, BinaryImagePart, RemoteImagePart, MentionPart)):
            if conversion or format_spec:
                msg = "outbound message parts do not support conversion or format specs"
                raise ValueError(msg)
            parts.append(value)
            continue
        if conversion:
            value = formatter.convert_field(value, conversion)
        _append_text_part(parts, formatter.format_field(value, format_spec or ""))
    return OutboundMessage(tuple(parts))


def _append_text_part(parts: list[MessagePart], text: str) -> None:
    if not text:
        return
    if parts and isinstance(parts[-1], TextPart):
        parts[-1] = TextPart(parts[-1].text + text)
        return
    parts.append(TextPart(text))


@dataclass(frozen=True, slots=True)
class ReplyContext:
    conversation: ConversationRef
    message_id: str
    sequence: str | None = None
    reply_deadline: datetime | None = None

    def __post_init__(self) -> None:
        if not self.message_id.strip():
            raise OutboundMessageError.empty_reply_message_id()
        if self.sequence is not None and not self.sequence.strip():
            raise OutboundMessageError.empty_reply_sequence()
        validate_reply_deadline(self.reply_deadline)

    @classmethod
    def from_message(cls, message: IncomingMessageRef) -> ReplyContext:
        """Reply to this event while retaining its transport delivery window."""

        return cls(
            message.conversation,
            message.message_id,
            sequence=message.sequence,
            reply_deadline=message.reply_deadline,
        )


@dataclass(frozen=True, slots=True)
class DeliveryCapabilities:
    can_reply_to_event: bool
    can_send_proactively: bool
    can_mention_members: bool
    supports_group_context: bool
    supports_private_context: bool
    supports_images: bool
    supports_interactive_prompts: bool = False


class DeliveryFailureKind(str, Enum):
    """Transport-neutral disposition for an unsuccessful delivery."""

    PERMANENT = "permanent"
    RETRYABLE = "retryable"
    UNCERTAIN = "uncertain"
    TRANSPORT_UNAVAILABLE = "transport_unavailable"


@dataclass(frozen=True, slots=True)
class SendResult:
    delivered: bool
    message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    trace_id: str | None = None
    failure_kind: DeliveryFailureKind | None = None

    def __post_init__(self) -> None:
        if self.delivered and not (self.message_id or "").strip():
            raise OutboundMessageError.missing_delivery_message_id()
        if not self.delivered and not (self.error_code or self.error_message):
            raise OutboundMessageError.missing_delivery_error()
        if self.delivered and self.failure_kind is not None:
            raise OutboundMessageError.successful_delivery_failure_kind()


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
