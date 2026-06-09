import sqlite3
from pathlib import Path

from nonebot import on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.feature_policy import is_superuser
from ironsbot.utils.rule import no_reply

from .config import plugin_config
from .text import build_message, normalize_command_text, render_text

COMMAND_PREFIXES = ("/",)
REPLY_LINE_LIMIT_ARG_KEY = "_message_reply_line_limit_arg"
REPLY_LINE_LIMIT_COMMANDS = (
    "回复行数",
    "消息行数",
    "设置回复行数",
    "设置消息行数",
)
REPLY_LINE_LIMIT_CLEAR_COMMANDS = {"默认", "清除", "重置", "不限", "无限", "0"}
TEXT_SEND_APIS = {"send_msg", "send_group_msg", "send_private_msg"}
TEXT_ONLY_SEGMENT_TYPES = {"text", "at"}


def _cache_path() -> Path:
    path = plugin_config.msg_reply_limit_path
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect_cache() -> sqlite3.Connection:
    conn = sqlite3.connect(_cache_path())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS group_reply_line_limits (
            group_id INTEGER PRIMARY KEY,
            max_lines INTEGER NOT NULL,
            updated_by INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def _default_reply_line_limit() -> int | None:
    value = plugin_config.msg_reply_default_lines
    if value <= 0:
        return None
    return max(
        plugin_config.msg_reply_min_lines,
        min(value, plugin_config.msg_reply_max_lines),
    )


def get_group_reply_line_limit(group_id: int) -> int | None:
    with _connect_cache() as conn:
        row = conn.execute(
            """
            SELECT max_lines FROM group_reply_line_limits
            WHERE group_id = ?
            """,
            (group_id,),
        ).fetchone()

    if row is None:
        return _default_reply_line_limit()
    return int(row[0])


def set_group_reply_line_limit(
    group_id: int,
    max_lines: int,
    updated_by: int,
) -> None:
    with _connect_cache() as conn:
        conn.execute(
            """
            INSERT INTO group_reply_line_limits
            (group_id, max_lines, updated_by)
            VALUES (?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                max_lines = excluded.max_lines,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (group_id, max_lines, updated_by),
        )
        conn.commit()


def clear_group_reply_line_limit(group_id: int) -> None:
    with _connect_cache() as conn:
        conn.execute(
            """
            DELETE FROM group_reply_line_limits
            WHERE group_id = ?
            """,
            (group_id,),
        )
        conn.commit()


def _strip_command_prefix(text: str) -> str | None:
    stripped = text.strip()
    for prefix in COMMAND_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def _parse_reply_line_limit_arg(command: str) -> str | None:
    stripped = command.strip()
    for prefix in sorted(REPLY_LINE_LIMIT_COMMANDS, key=len, reverse=True):
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


async def _is_reply_line_limit_command(event: Event, state: T_State) -> bool:
    command = _strip_command_prefix(event.get_plaintext())
    if command is None:
        return False

    arg = _parse_reply_line_limit_arg(command)
    if arg is None:
        return False

    state[REPLY_LINE_LIMIT_ARG_KEY] = arg
    return True


def _can_manage_reply_line_limit(event: GroupMessageEvent) -> bool:
    role = str(getattr(event.sender, "role", "") or "")
    return is_superuser(event.user_id) or role in {"owner", "admin"}


def _reply_line_limit_for_event(event: MessageEvent | None) -> int | None:
    if isinstance(event, GroupMessageEvent):
        return get_group_reply_line_limit(event.group_id)
    return _default_reply_line_limit()


def reply_line_limit_for_target(
    *,
    group_id: int | None = None,
) -> int | None:
    if group_id is not None:
        return get_group_reply_line_limit(group_id)
    return _default_reply_line_limit()


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


def limit_message_by_reply_lines(
    message: str | Message,
    *,
    event: MessageEvent | None = None,
    group_id: int | None = None,
) -> str | Message:
    if isinstance(message, Message):
        return message

    max_lines = (
        reply_line_limit_for_target(group_id=group_id)
        if group_id is not None
        else _reply_line_limit_for_event(event)
    )
    return limit_text_lines(message, max_lines)


def _limit_onebot_message(
    message: object,
    *,
    group_id: int | None,
) -> object:
    max_lines = reply_line_limit_for_target(group_id=group_id)
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


def _api_group_id(api: str, data: dict[str, object]) -> int | None:
    if api not in {"send_msg", "send_group_msg"}:
        return None
    if api == "send_msg" and data.get("message_type") != "group":
        return None

    raw_group_id = data.get("group_id")
    try:
        return int(raw_group_id) if raw_group_id is not None else None
    except (TypeError, ValueError):
        return None


@Bot.on_calling_api
async def _limit_reply_lines_before_send(
    bot: Bot,  # noqa: ARG001
    api: str,
    data: dict[str, object],
) -> None:
    if api not in TEXT_SEND_APIS:
        return

    message = data.get("message")
    if message is None:
        return

    data["message"] = _limit_onebot_message(
        message,
        group_id=_api_group_id(api, data),
    )


reply_line_limit_matcher = on_message(
    rule=Rule(_is_reply_line_limit_command) & no_reply(),
    priority=5,
    block=True,
)


async def _finish_reply_line_limit(
    event: MessageEvent,
    message: str | Message,
) -> None:
    at_user_ids = (event.user_id,) if isinstance(event, GroupMessageEvent) else ()
    await reply_line_limit_matcher.finish(
        build_message(message, at_user_ids=at_user_ids)
    )


@reply_line_limit_matcher.handle()
async def handle_reply_line_limit_command(
    event: MessageEvent,
    state: T_State,
) -> None:
    if not isinstance(event, GroupMessageEvent):
        await _finish_reply_line_limit(event, "请在群聊中设置本群回复行数。")

    raw_arg = str(state.get(REPLY_LINE_LIMIT_ARG_KEY) or "").strip()
    current_limit = get_group_reply_line_limit(event.group_id)
    current_text = "不限制" if current_limit is None else f"{current_limit} 行"

    if not raw_arg:
        await _finish_reply_line_limit(
            event,
            f"当前本群回复消息行数：{current_text}\n"
            "用法：/回复行数 20；发送 /回复行数 默认 可恢复默认。"
        )

    if not _can_manage_reply_line_limit(event):
        await _finish_reply_line_limit(
            event,
            "只有本群群主、管理员或超级管理员可以修改回复行数。"
        )

    normalized_arg = normalize_command_text(raw_arg)
    if normalized_arg in REPLY_LINE_LIMIT_CLEAR_COMMANDS:
        clear_group_reply_line_limit(event.group_id)
        await _finish_reply_line_limit(
            event,
            "已恢复本群回复消息行数默认设置。"
        )

    if not raw_arg.isdigit():
        await _finish_reply_line_limit(
            event,
            "回复行数需要是数字，例如：/回复行数 20"
        )

    max_lines = int(raw_arg)
    min_lines = plugin_config.msg_reply_min_lines
    max_allowed_lines = plugin_config.msg_reply_max_lines
    if max_lines < min_lines or max_lines > max_allowed_lines:
        await _finish_reply_line_limit(
            event,
            f"回复行数范围是 {min_lines} ~ {max_allowed_lines}。"
        )

    set_group_reply_line_limit(
        event.group_id,
        max_lines,
        event.user_id,
    )
    await _finish_reply_line_limit(
        event,
        f"已设置本群回复消息行数：{max_lines} 行。"
    )
