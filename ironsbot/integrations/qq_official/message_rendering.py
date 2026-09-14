# SPDX-License-Identifier: MIT
"""Render platform-neutral messages into Tencent SDK send operations."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

from ironsbot.core.outbound import (
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    TextPart,
)
from ironsbot.core.platform import ConversationRef, Platform

if TYPE_CHECKING:
    from ironsbot.core.interactive_prompts import PromptSession


class QQOfficialOutboundMessageError(ValueError):
    @classmethod
    def unsupported_mention(cls) -> QQOfficialOutboundMessageError:
        return cls("QQ Official mentions require a member in the current group")

    @classmethod
    def unsupported_part(cls, part: object) -> QQOfficialOutboundMessageError:
        return cls(f"Unsupported outbound part: {type(part).__name__}")

    @classmethod
    def prompt_requires_text(cls) -> QQOfficialOutboundMessageError:
        return cls("QQ Official interactive prompts require a text payload")


@dataclass(frozen=True, slots=True)
class QQOfficialTextPayload:
    content: str
    prompt: PromptSession | None = None


@dataclass(frozen=True, slots=True)
class QQOfficialImagePayload:
    content: bytes | None = None
    url: str | None = None
    filename: str = "ironsbot.png"


QQOfficialPayload = QQOfficialTextPayload | QQOfficialImagePayload


def render_qq_official_outbound_message(
    message: OutboundMessage,
    *,
    conversation: ConversationRef,
) -> tuple[QQOfficialPayload, ...]:
    """Preserve ordered text/mention runs and individual image payloads."""

    rendered: list[QQOfficialPayload] = []
    text: list[str] = []

    def flush_text() -> None:
        content = "".join(text)
        text.clear()
        if content:
            rendered.append(QQOfficialTextPayload(content))

    for part in message.parts:
        if isinstance(part, TextPart):
            text.append(part.text)
        elif isinstance(part, MentionPart):
            if not _supports_group_mention(conversation, part):
                raise QQOfficialOutboundMessageError.unsupported_mention()
            text.append(f'<qqbot-at-user id="{escape(part.actor.id, quote=True)}" />')
        elif isinstance(part, BinaryImagePart):
            flush_text()
            rendered.append(
                QQOfficialImagePayload(
                    content=part.content,
                    filename=part.filename or _image_filename(part.content_type),
                )
            )
        elif isinstance(part, RemoteImagePart):
            flush_text()
            rendered.append(QQOfficialImagePayload(url=part.url))
        else:
            raise QQOfficialOutboundMessageError.unsupported_part(part)
    flush_text()
    _attach_prompt(rendered, message.prompt)
    return tuple(rendered)


def _attach_prompt(
    rendered: list[QQOfficialPayload],
    prompt: PromptSession | None,
) -> None:
    if prompt is None:
        return
    for index, payload in enumerate(rendered):
        if isinstance(payload, QQOfficialTextPayload):
            rendered[index] = QQOfficialTextPayload(payload.content, prompt=prompt)
            return
    raise QQOfficialOutboundMessageError.prompt_requires_text()


def _supports_group_mention(
    conversation: ConversationRef,
    part: MentionPart,
) -> bool:
    return (
        conversation.platform is Platform.QQ_OFFICIAL
        and conversation.kind == "group"
        and part.actor.platform is Platform.QQ_OFFICIAL
        and part.actor.kind == "member"
        and part.actor.scope_id == conversation.id
        and part.actor.account_id == conversation.account_id
    )


def _image_filename(content_type: str) -> str:
    extension = {
        "image/gif": "gif",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(content_type.lower(), "bin")
    return f"ironsbot.{extension}"
