# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent

from ironsbot.runtime.commands import CommandContext

_AT_PATTERNS = (
    re.compile(r"\[CQ:at,qq=([^\]]+)\]"),
    re.compile(r"\[at:qq=([^\],\]]+)"),
)
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


def _message_has_bot_at(message: Any, self_id: str) -> bool:
    return bool(message) and any(
        getattr(segment, "type", "") == "at"
        and str(getattr(segment, "data", {}).get("qq", "")) == self_id
        for segment in message
    )


def mentions_bot(event: GroupMessageEvent) -> bool:
    if event.reply is not None:
        return False

    self_id = str(event.self_id or "")
    if not self_id:
        return False
    if _message_has_bot_at(event.get_message(), self_id) or _message_has_bot_at(
        event.original_message,
        self_id,
    ):
        return True
    if any(
        match.group(1).strip() == self_id
        for pattern in _AT_PATTERNS
        for match in pattern.finditer(str(event.raw_message or ""))
    ):
        return True
    return bool(event.is_tome())


async def build_notice_source(
    event: MessageEvent,
    prompt: str,
    group_aliases: Mapping[str, int],
    *,
    bot: Bot | None = None,
) -> str:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        lines = ["会话：私聊"]
    else:
        group_id = int(group_id)
        group_name = await _group_name(bot, group_id)
        alias = next(
            (
                name
                for name, alias_id in group_aliases.items()
                if int(alias_id) == group_id
            ),
            "",
        )
        label = group_name or alias
        group_label = f"{label}（{group_id}）" if label else str(group_id)
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


async def _group_name(bot: Bot | None, group_id: int) -> str:
    if bot is None:
        return ""
    try:
        info = await bot.get_group_info(group_id=group_id, no_cache=False)
    except Exception:  # noqa: BLE001
        return ""
    return str(
        info.get("group_name", "")
        if isinstance(info, dict)
        else getattr(info, "group_name", "")
    ).strip()
