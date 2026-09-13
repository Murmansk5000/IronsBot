# SPDX-License-Identifier: MIT
"""Render platform-neutral outbound values for QQ Official Bot."""

from __future__ import annotations

from nonebot.adapters.qq import Message, MessageSegment

from ironsbot.core.outbound import (
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    TextPart,
)
from ironsbot.core.platform import ConversationRef, Platform


class QQOfficialOutboundMessageError(ValueError):
    @classmethod
    def unsupported_mention(cls) -> QQOfficialOutboundMessageError:
        return cls("QQ Official mentions require a member in the current group")

    @classmethod
    def unsupported_part(cls, part: object) -> QQOfficialOutboundMessageError:
        return cls(f"Unsupported outbound part: {type(part).__name__}")


def render_qq_official_outbound_message(
    message: OutboundMessage,
    *,
    conversation: ConversationRef,
) -> Message:
    rendered = Message()
    for part in message.parts:
        if isinstance(part, TextPart):
            rendered += MessageSegment.text(part.text)
        elif isinstance(part, BinaryImagePart):
            rendered += MessageSegment.file_image(
                part.content,
                file_name=part.filename or _image_filename(part.content_type),
            )
        elif isinstance(part, RemoteImagePart):
            rendered += MessageSegment.image(part.url)
        elif isinstance(part, MentionPart):
            if not _supports_group_mention(conversation, part):
                raise QQOfficialOutboundMessageError.unsupported_mention()
            rendered += MessageSegment.mention_user(part.actor.id)
        else:
            raise QQOfficialOutboundMessageError.unsupported_part(part)
    return rendered


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
    )


def _image_filename(content_type: str) -> str:
    extension = {
        "image/gif": "gif",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(content_type.lower(), "bin")
    return f"ironsbot.{extension}"
