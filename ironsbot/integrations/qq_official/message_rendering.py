# SPDX-License-Identifier: MIT
"""Render platform-neutral messages into Tencent SDK send operations."""

from __future__ import annotations

import re
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


@dataclass(frozen=True, slots=True)
class QQOfficialTextPayload:
    content: str
    prompt: PromptSession | None = None
    reference_id: str | None = None
    markdown: bool = False


@dataclass(frozen=True, slots=True)
class QQOfficialImagePayload:
    content: bytes | None = None
    url: str | None = None
    filename: str = "ironsbot.png"
    reference_id: str | None = None


QQOfficialPayload = QQOfficialTextPayload | QQOfficialImagePayload

_MARKDOWN_MENU_NUMBER = re.compile(
    r"(?m)^(?P<prefix>[ \t]*(?:↳[ \t]*)?)(?P<number>\d+)\.(?=[ \t])"
)


def render_qq_official_outbound_message(
    message: OutboundMessage,
    *,
    conversation: ConversationRef | None = None,
    supports_interactive_prompts: bool = False,
) -> tuple[QQOfficialPayload, ...]:
    """Compact text around media into the fewest supported QQ messages."""

    images: list[QQOfficialImagePayload] = []
    mentions: list[str] = []
    text: list[str] = []
    saw_image = False
    text_after_image = False
    for part in message.parts:
        if isinstance(part, TextPart):
            text.append(part.text)
            if saw_image:
                text_after_image = True
        elif isinstance(part, MentionPart):
            mentions.append(_render_mention(conversation, part))
            if saw_image:
                text_after_image = True
        elif isinstance(part, (BinaryImagePart, RemoteImagePart)):
            saw_image = True
            images.append(_render_image(part))
        else:
            raise QQOfficialOutboundMessageError.unsupported_part(part)
    text_payloads: list[QQOfficialPayload] = []
    if mentions:
        rendered_text = _escape_markdown_menu_numbers("".join(text))
        text_payloads.append(
            QQOfficialTextPayload(
                _join_markdown_mention_and_text(mentions, rendered_text),
                markdown=True,
            )
        )
    elif text:
        text_payloads.append(QQOfficialTextPayload("".join(text)))
    rendered = (
        [*images, *text_payloads] if text_after_image else [*text_payloads, *images]
    )
    if supports_interactive_prompts:
        _attach_prompt(rendered, message.prompt)
    return tuple(rendered)


def _join_markdown_mention_and_text(
    mentions: list[str],
    text: str,
) -> str:
    mention_text = "".join(mentions)
    if not text:
        return mention_text
    if text.startswith("\n"):
        return f"{mention_text}{text}"
    body = text.lstrip(" \t")
    return f"{mention_text}\n{body}"


def _escape_markdown_menu_numbers(text: str) -> str:
    """Keep numbered menu labels literal in QQ Markdown, including exit item 0."""

    return _MARKDOWN_MENU_NUMBER.sub(
        lambda match: f"{match.group('prefix')}{match.group('number')}\\.",
        text,
    )


def _attach_prompt(
    rendered: list[QQOfficialPayload],
    prompt: PromptSession | None,
) -> None:
    if prompt is None:
        return
    for index, payload in enumerate(rendered):
        if isinstance(payload, QQOfficialTextPayload) and not payload.markdown:
            rendered[index] = QQOfficialTextPayload(
                payload.content,
                prompt=prompt,
                reference_id=payload.reference_id,
                markdown=payload.markdown,
            )
            return
    for index, payload in enumerate(rendered):
        if isinstance(payload, QQOfficialTextPayload):
            rendered[index] = QQOfficialTextPayload(
                payload.content,
                prompt=prompt,
                reference_id=payload.reference_id,
                markdown=payload.markdown,
            )
            return
    rendered.append(QQOfficialTextPayload(_prompt_text(prompt), prompt=prompt))


def _prompt_text(prompt: PromptSession) -> str:
    choices = "\n".join(f"{choice.id}. {choice.label}" for choice in prompt.choices)
    return f"请选择：\n{choices}\n\n回复序号选择"


def _supports_group_mention(
    conversation: ConversationRef | None,
    part: MentionPart,
) -> bool:
    return (
        conversation is not None
        and conversation.platform is Platform.QQ_OFFICIAL
        and conversation.kind == "group"
        and part.actor.platform is Platform.QQ_OFFICIAL
        and part.actor.kind == "member"
        and part.actor.scope_id == conversation.id
        and part.actor.account_id == conversation.account_id
    )


def _render_mention(
    conversation: ConversationRef | None,
    part: MentionPart,
) -> str:
    if not _supports_group_mention(conversation, part):
        raise QQOfficialOutboundMessageError.unsupported_mention()
    return f'<qqbot-at-user id="{escape(part.actor.id, quote=True)}" />'


def _render_image(
    part: BinaryImagePart | RemoteImagePart,
) -> QQOfficialImagePayload:
    if isinstance(part, RemoteImagePart):
        return QQOfficialImagePayload(url=part.url)
    return QQOfficialImagePayload(
        content=part.content,
        filename=part.filename or _image_filename(part.content_type),
    )


def _image_filename(content_type: str) -> str:
    extension = {
        "image/gif": "gif",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(content_type.lower(), "bin")
    return f"ironsbot.{extension}"
