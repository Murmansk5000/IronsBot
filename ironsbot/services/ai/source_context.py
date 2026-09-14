# SPDX-License-Identifier: MIT
"""Platform-neutral source details for AI failure notices."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext

NOTICE_MESSAGE_MAX_CHARS = 300


def format_ai_source_context(context: MessageInputContext) -> str:
    message = context.message
    conversation = message.conversation
    lines = [
        f"平台：{message.platform.value}",
        f"会话：{conversation.kind} {conversation.id}",
        f"用户：{message.actor.id}",
        f"消息ID：{message.message_id}",
    ]
    text = " ".join(message.text.strip().split())
    if len(text) > NOTICE_MESSAGE_MAX_CHARS:
        text = text[:NOTICE_MESSAGE_MAX_CHARS].rstrip() + "..."
    lines.append(f"消息：{text or '（空）'}")
    return "\n".join(lines)
