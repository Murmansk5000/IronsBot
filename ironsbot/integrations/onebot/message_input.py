# SPDX-License-Identifier: MIT
"""Extract native event facts for the framework-free OneBot decoder."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ironsbot.integrations.onebot.message_facts import (
    OneBotMessageFacts,
    decode_onebot_message,
)
from ironsbot.integrations.onebot.message_segments import onebot_message_text

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.integrations.onebot.message_segments import OneBotSegment


class OneBotMessageInputError(ValueError):
    @classmethod
    def missing_user_id(cls) -> OneBotMessageInputError:
        return cls("OneBot message event has no user_id")

    @classmethod
    def missing_message_id(cls) -> OneBotMessageInputError:
        return cls("OneBot message event has no message_id")

    @classmethod
    def missing_reply_message_id(cls) -> OneBotMessageInputError:
        return cls("OneBot reply metadata has no message_id")


def message_input_context(event: Event) -> MessageInputContext:
    """Read the current native message without importing its quoted body.

    ``event.reply`` is metadata for a different message. Its text and ``@``
    segments deliberately never participate here.
    """

    return decode_onebot_message(message_input_facts(event))


def message_input_facts(event: Event) -> OneBotMessageFacts:
    to_me = getattr(event, "is_tome", False)
    segments = _segments(getattr(event, "message", None))
    original_segments = _segments(getattr(event, "original_message", None))
    text = onebot_message_text(segments)
    group_id = (
        getattr(event, "group_id", None)
        if getattr(event, "message_type", None) == "group"
        else None
    )
    sender = getattr(event, "sender", None)
    role = getattr(sender, "role", None)
    reply = getattr(event, "reply", None)
    reply_id = getattr(reply, "message_id", None)
    if reply is not None and reply_id is None:
        raise OneBotMessageInputError.missing_reply_message_id()
    reply_sender = getattr(getattr(reply, "sender", None), "user_id", None)
    return OneBotMessageFacts(
        account_id=str(getattr(event, "self_id", "") or "").strip(),
        user_id=_event_user_id(event),
        message_id=_message_id(event),
        text=text,
        segments=segments,
        original_segments=original_segments,
        group_id=str(group_id) if group_id is not None else None,
        group_role=str(role) if group_id is not None and role is not None else None,
        reply_to_id=str(reply_id) if reply_id is not None else None,
        reply_sender_id=str(reply_sender) if reply_sender is not None else None,
        raw_message=str(getattr(event, "raw_message", "") or ""),
        addressed_to_bot=group_id is not None
        and bool(to_me() if callable(to_me) else to_me),
        actor_display_name=str(
            getattr(sender, "nickname", "") or getattr(sender, "card", "") or ""
        ),
    )


def _segments(message: Any) -> tuple[OneBotSegment, ...]:
    return tuple(
        {"type": segment["type"], "data": segment["data"]}
        if isinstance(segment, Mapping)
        else {
            "type": getattr(segment, "type", ""),
            "data": getattr(segment, "data", {}),
        }
        for segment in (message or ())
    )


def _message_id(event: Event) -> str:
    value = getattr(event, "message_id", None)
    if value is None:
        raise OneBotMessageInputError.missing_message_id()
    return str(value)


def _event_user_id(event: Event) -> str:
    value = getattr(event, "user_id", None)
    if value is None:
        raise OneBotMessageInputError.missing_user_id()
    return str(value)
