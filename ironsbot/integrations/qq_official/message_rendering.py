# SPDX-License-Identifier: MIT
"""Render platform-neutral messages into Tencent SDK send operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.outbound import (
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    TextPart,
)

if TYPE_CHECKING:
    from ironsbot.core.interactive_prompts import PromptSession


class QQOfficialOutboundMessageError(ValueError):
    @classmethod
    def unsupported_mention(cls) -> QQOfficialOutboundMessageError:
        return cls("QQ Official does not provide reliable visible member mentions")

    @classmethod
    def unsupported_part(cls, part: object) -> QQOfficialOutboundMessageError:
        return cls(f"Unsupported outbound part: {type(part).__name__}")


@dataclass(frozen=True, slots=True)
class QQOfficialTextPayload:
    content: str
    prompt: PromptSession | None = None
    reference_id: str | None = None


@dataclass(frozen=True, slots=True)
class QQOfficialImagePayload:
    content: bytes | None = None
    url: str | None = None
    filename: str = "ironsbot.png"
    reference_id: str | None = None


QQOfficialPayload = QQOfficialTextPayload | QQOfficialImagePayload


def render_qq_official_outbound_message(
    message: OutboundMessage,
    *,
    supports_interactive_prompts: bool = False,
) -> tuple[QQOfficialPayload, ...]:
    """Compact text around media into the fewest supported QQ messages."""

    images: list[QQOfficialImagePayload] = []
    text: list[str] = []
    saw_image = False
    text_after_image = False
    for part in message.parts:
        if isinstance(part, TextPart):
            text.append(part.text)
            if saw_image:
                text_after_image = True
        elif isinstance(part, MentionPart):
            raise QQOfficialOutboundMessageError.unsupported_mention()
        elif isinstance(part, BinaryImagePart):
            saw_image = True
            images.append(
                QQOfficialImagePayload(
                    content=part.content,
                    filename=part.filename or _image_filename(part.content_type),
                )
            )
        elif isinstance(part, RemoteImagePart):
            saw_image = True
            images.append(QQOfficialImagePayload(url=part.url))
        else:
            raise QQOfficialOutboundMessageError.unsupported_part(part)
    text_payloads: list[QQOfficialPayload] = (
        [QQOfficialTextPayload("".join(text))] if text else []
    )
    rendered = (
        [*images, *text_payloads] if text_after_image else [*text_payloads, *images]
    )
    if supports_interactive_prompts:
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
            rendered[index] = QQOfficialTextPayload(
                payload.content,
                prompt=prompt,
                reference_id=payload.reference_id,
            )
            return
    rendered.append(QQOfficialTextPayload(_prompt_text(prompt), prompt=prompt))


def _prompt_text(prompt: PromptSession) -> str:
    choices = "\n".join(f"{choice.id}. {choice.label}" for choice in prompt.choices)
    return f"请选择：\n{choices}\n\n回复序号选择"


def _image_filename(content_type: str) -> str:
    extension = {
        "image/gif": "gif",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(content_type.lower(), "bin")
    return f"ironsbot.{extension}"
