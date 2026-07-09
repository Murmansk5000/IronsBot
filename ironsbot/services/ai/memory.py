import sqlite3
import time
from contextlib import AbstractContextManager
from pathlib import Path

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.log import logger

from ironsbot.config.loader import get_app_config
from ironsbot.services.ai.history import HistoryMessage
from ironsbot.shared.sqlite import open_sqlite_schema

AI_MEMORY_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        session_key TEXT NOT NULL,
        chat_scope TEXT NOT NULL,
        chat_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_memory_user_time
    ON messages (user_id, created_at DESC)
    """,
)


def _get_ai_config():
    return get_app_config().ai


def _memory_path() -> Path:
    return _get_ai_config().memory_path


def _connect() -> AbstractContextManager[sqlite3.Connection]:
    return open_sqlite_schema(_memory_path(), AI_MEMORY_SCHEMA)


def _is_memory_enabled() -> bool:
    config = _get_ai_config()
    return config.memory and config.memory_turns > 0


def _event_context(event: MessageEvent) -> tuple[str, int]:
    if isinstance(event, GroupMessageEvent):
        return "group", int(event.group_id)

    return "private", int(event.user_id)


def append_user_memory(
    event: MessageEvent,
    *,
    session_key: str,
    prompt: str,
    reply: str,
) -> None:
    if not _is_memory_enabled():
        return

    chat_scope, chat_id = _event_context(event)
    now = time.time()
    rows = (
        (
            int(event.user_id),
            session_key,
            chat_scope,
            chat_id,
            "user",
            prompt,
            now,
        ),
        (
            int(event.user_id),
            session_key,
            chat_scope,
            chat_id,
            "assistant",
            reply,
            now + 0.001,
        ),
    )

    try:
        with _connect() as conn:
            conn.executemany(
                """
                INSERT INTO messages (
                    user_id, session_key, chat_scope, chat_id,
                    role, content, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
    except sqlite3.Error as e:
        logger.warning(f"failed to write AI memory for {event.user_id}: {e}")


def get_user_memory(
    event: MessageEvent,
    *,
    current_session_key: str,
    has_short_history: bool,
) -> list[HistoryMessage]:
    if not _is_memory_enabled():
        return []

    message_limit = _get_ai_config().memory_turns * 2
    sql = (
        "SELECT role, content "
        "FROM messages "
        "WHERE user_id = ? "
    )
    params: list[object] = [int(event.user_id)]
    if has_short_history:
        sql += "AND session_key != ? "
        params.append(current_session_key)

    sql += "ORDER BY created_at DESC LIMIT ?"
    params.append(message_limit)

    try:
        with _connect() as conn:
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as e:
        logger.warning(f"failed to read AI memory for {event.user_id}: {e}")
        return []

    messages = [
        {"role": str(role), "content": str(content)}
        for role, content in reversed(rows)
    ]
    return _trim_memory_chars(messages)


def _trim_memory_chars(messages: list[HistoryMessage]) -> list[HistoryMessage]:
    max_chars = _get_ai_config().memory_max_chars
    used = 0
    selected: list[HistoryMessage] = []

    for message in reversed(messages):
        content = message.get("content", "")
        next_used = used + len(content)
        if selected and next_used > max_chars:
            break

        used = next_used
        selected.append(message)

    return list(reversed(selected))
