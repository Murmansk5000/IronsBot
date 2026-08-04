# SPDX-License-Identifier: MIT
"""Rendering of platform-neutral outbound values for OneBot v11."""

from __future__ import annotations

from base64 import b64encode

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.outbound import (
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    TextPart,
)
from ironsbot.core.platform import ConversationRef, Platform


class OneBotOutboundMessageError(ValueError):
    @classmethod
    def unsupported_mention(cls) -> OneBotOutboundMessageError:
        return cls("OneBot mentions require a numeric group member")

    @classmethod
    def unsupported_part(cls, part: object) -> OneBotOutboundMessageError:
        return cls(f"Unsupported outbound part: {type(part).__name__}")

    @classmethod
    def invalid_reply_id(cls) -> OneBotOutboundMessageError:
        return cls("OneBot reply message IDs must be numeric")


def render_onebot_outbound_message(
    message: OutboundMessage,
    *,
    conversation: ConversationRef | None = None,
    reply_to_id: str | None = None,
) -> Message:
    """Render core message parts after the caller has selected a OneBot target."""

    rendered = Message()
    if reply_to_id is not None:
        rendered += MessageSegment.reply(_onebot_id(reply_to_id))
    for part in message.parts:
        if isinstance(part, TextPart):
            rendered += MessageSegment.text(part.text)
        elif isinstance(part, BinaryImagePart):
            encoded = b64encode(part.content).decode("ascii")
            rendered += MessageSegment.image(f"base64://{encoded}")
        elif isinstance(part, RemoteImagePart):
            rendered += MessageSegment.image(part.url)
        elif isinstance(part, MentionPart):
            if not _supports_group_mention(conversation, part):
                raise OneBotOutboundMessageError.unsupported_mention()
            rendered += MessageSegment.at(int(part.actor.id))
        else:
            raise OneBotOutboundMessageError.unsupported_part(part)
    return rendered


def _supports_group_mention(
    conversation: ConversationRef | None,
    part: MentionPart,
) -> bool:
    return (
        conversation is not None
        and conversation.platform is Platform.ONEBOT
        and conversation.kind == "group"
        and part.actor.platform is Platform.ONEBOT
        and part.actor.id.isdecimal()
    )


def _onebot_id(value: str) -> int:
    if not value.isdecimal():
        raise OneBotOutboundMessageError.invalid_reply_id()
    return int(value)
