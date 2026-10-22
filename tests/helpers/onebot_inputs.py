"""Build test contexts from synthetic events using the production wire decoder."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.integrations.onebot.message_envelope import decode_received_message
from ironsbot.integrations.onebot.message_facts import (
    OneBotMessageFacts,
    decode_onebot_message,
)
from ironsbot.integrations.onebot.message_segments import onebot_message_text

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent

    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.message_input import MessageInputContext


def message_input_facts(event: MessageEvent) -> OneBotMessageFacts:
    envelope = decode_received_message(event.model_dump())
    assert envelope is not None, "invalid synthetic OneBot message envelope"
    group_id = envelope.group_id if envelope.message_type == "group" else None
    sender, reply = envelope.sender, envelope.reply
    return OneBotMessageFacts(
        account_id=str(envelope.self_id),
        user_id=str(envelope.user_id),
        message_id=str(envelope.message_id),
        text=onebot_message_text(envelope.message),
        segments=tuple(envelope.message),
        original_segments=tuple(
            (envelope.model_extra or {}).get("original_message", ())
        ),
        group_id=str(group_id) if group_id is not None else None,
        group_role=sender.role if group_id is not None and sender is not None else None,
        reply_to_id=str(reply.message_id) if reply is not None else None,
        reply_sender_id=(
            str(reply.sender.user_id)
            if reply is not None and reply.sender.user_id is not None
            else None
        ),
        raw_message=envelope.raw_message,
        addressed_to_bot=group_id is not None and envelope.to_me,
        actor_display_name=(sender.nickname or sender.card or "")
        if sender is not None
        else "",
    )


def message_input_context(event: MessageEvent) -> MessageInputContext:
    return decode_onebot_message(message_input_facts(event))


def command_context(event: MessageEvent) -> CommandContext:
    return command_context_from_input(message_input_context(event))
