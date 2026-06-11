# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.shared.features import is_superuser

from .text import normalize_command_text, render_text

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

REPLY_LINE_LIMIT_COMMANDS = (
    "回复行数",
    "消息行数",
    "设置回复行数",
    "设置消息行数",
)
REPLY_LINE_LIMIT_CLEAR_COMMANDS = {"默认", "清除", "重置", "不限", "无限", "-1"}
TEXT_SEND_APIS = {"send_msg", "send_group_msg", "send_private_msg"}
TEXT_ONLY_SEGMENT_TYPES = {"text", "at"}


@dataclass(frozen=True, slots=True)
class ReplyLineLimitDecision:
    message: str
    max_lines: int | None = None
    should_clear: bool = False
    should_set: bool = False


def parse_reply_line_limit_arg(command: str) -> str | None:
    stripped = command.strip()
    for prefix in sorted(REPLY_LINE_LIMIT_COMMANDS, key=len, reverse=True):
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def can_manage_reply_line_limit(event: GroupMessageEvent) -> bool:
    role = str(getattr(event.sender, "role", "") or "")
    return is_superuser(event.user_id) or role in {"owner", "admin"}


def build_reply_line_limit_decision(
    *,
    raw_arg: str,
    current_limit: int | None,
    can_manage: bool,
    min_lines: int,
    max_allowed_lines: int,
) -> ReplyLineLimitDecision:
    current_text = "不限制" if current_limit is None else f"{current_limit} 行"

    if not raw_arg:
        return ReplyLineLimitDecision(
            message=(
                f"当前本群回复消息行数：{current_text}\n"
                "用法：/回复行数 20；发送 /回复行数 -1 可恢复默认。"
            )
        )

    if not can_manage:
        return ReplyLineLimitDecision(
            message="只有本群群主、管理员或超级管理员可以修改回复行数。"
        )

    normalized_arg = normalize_command_text(raw_arg)
    if normalized_arg in REPLY_LINE_LIMIT_CLEAR_COMMANDS:
        return ReplyLineLimitDecision(
            message="已恢复本群回复消息行数默认设置。",
            should_clear=True,
        )

    if not raw_arg.isdigit():
        return ReplyLineLimitDecision(
            message="回复行数需要是数字，例如：/回复行数 20"
        )

    max_lines = int(raw_arg)
    if max_lines < min_lines or max_lines > max_allowed_lines:
        return ReplyLineLimitDecision(
            message=f"回复行数范围是 {min_lines} ~ {max_allowed_lines}。"
        )

    return ReplyLineLimitDecision(
        message=f"已设置本群回复消息行数：{max_lines} 行。",
        max_lines=max_lines,
        should_set=True,
    )


def limit_text_lines(text: str, max_lines: int | None) -> str:
    rendered = render_text(text)
    if max_lines is None or max_lines <= 0:
        return rendered

    lines = rendered.splitlines()
    if len(lines) <= max_lines:
        return rendered

    visible_count = max(1, max_lines - 1)
    hidden_count = len(lines) - visible_count
    return "\n".join(
        [
            *lines[:visible_count],
            f"...还有 {hidden_count} 行未显示",
        ]
    )


def limit_onebot_message(
    message: object,
    *,
    max_lines: int | None,
) -> object:
    if max_lines is None or max_lines <= 0:
        return message

    if isinstance(message, str):
        return limit_text_lines(message, max_lines)

    if not isinstance(message, Message):
        return message

    if any(segment.type not in TEXT_ONLY_SEGMENT_TYPES for segment in message):
        return message

    has_at = any(segment.type == "at" for segment in message)
    text = "".join(
        str(segment.data.get("text", ""))
        for segment in message
        if segment.type == "text"
    )
    text_to_limit = text.lstrip() if has_at else text
    limited_text = limit_text_lines(text_to_limit, max_lines)
    if limited_text == text_to_limit:
        return message

    limited_message = Message()
    for segment in message:
        if segment.type == "at":
            limited_message += segment
            limited_message += MessageSegment.text(" ")

    limited_message += MessageSegment.text(limited_text)
    return limited_message


def group_id_for_send_api(api: str, data: dict[str, object]) -> int | None:
    if api not in {"send_msg", "send_group_msg"}:
        return None
    if api == "send_msg" and data.get("message_type") != "group":
        return None

    raw_group_id = data.get("group_id")
    try:
        return int(raw_group_id) if raw_group_id is not None else None
    except (TypeError, ValueError):
        return None
