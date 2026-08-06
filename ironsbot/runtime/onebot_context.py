# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.onebot_group_identity import (
    format_group_label,
    resolve_group_name,
)
from ironsbot.runtime.commands import CommandContext
from ironsbot.runtime.message_input import message_input_context

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent

NOTICE_MESSAGE_MAX_CHARS = 300


def event_group_id(event: MessageEvent) -> int | None:
    group_id = getattr(event, "group_id", None)
    return int(group_id) if group_id is not None else None


def command_context(event: MessageEvent) -> CommandContext:
    """Adapt a OneBot message event to the platform-neutral command context."""

    sender = getattr(event, "sender", None)
    role = getattr(sender, "role", None)
    return CommandContext(
        user_id=int(event.user_id),
        group_id=event_group_id(event),
        group_role=str(role) if role is not None else None,
    )


def mentions_bot(event: GroupMessageEvent) -> bool:
    context = message_input_context(event)
    return context.mentions_bot and not context.is_reply


async def build_notice_source(
    event: MessageEvent,
    prompt: str,
    *,
    bot: Bot | None = None,
) -> str:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        lines = ["会话：私聊"]
    else:
        group_id = int(group_id)
        group_label = format_group_label(
            group_id,
            await resolve_group_name(bot, group_id),
        )
        lines = [f"群：{group_label}"]

    sender = getattr(event, "sender", None)
    sender_name = str(
        getattr(sender, "card", "") or getattr(sender, "nickname", "") or ""
    ).strip()
    user_label = str(event.user_id)
    if sender_name:
        user_label += f"（{sender_name}）"
    lines.append(f"用户：{user_label}")

    message_id = getattr(event, "message_id", None)
    if message_id is not None:
        lines.append(f"消息ID：{message_id}")

    text = " ".join((prompt.strip() or event.get_plaintext().strip()).split())
    if len(text) > NOTICE_MESSAGE_MAX_CHARS:
        text = text[:NOTICE_MESSAGE_MAX_CHARS].rstrip() + "..."
    lines.append(f"消息：{text or '（空）'}")
    return "\n".join(lines)
