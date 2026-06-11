import sqlite3
import time
from pathlib import Path

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.log import logger

from .config import get_ai_config
from .history import HistoryMessage


def _memory_path() -> Path:
    return get_ai_config().memory_path


def _connect() -> sqlite3.Connection:
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
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
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ai_memory_user_time
        ON messages (user_id, created_at DESC)
        """
    )
    return conn


def _is_memory_enabled() -> bool:
    config = get_ai_config()
    return config.memory and config.memory_turns > 0


def _event_context(event: MessageEvent) -> tuple[str, int]:
    if isinstance(event, GroupMessageEvent):
        return "group", int(event.group_id)

    return "private", int(event.user_id)


def reset_user_memory(user_id: int) -> None:
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM messages WHERE user_id = ?", (int(user_id),))
    except sqlite3.Error as e:
        logger.warning(f"failed to reset AI memory for {user_id}: {e}")


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

    message_limit = get_ai_config().memory_turns * 2
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
    max_chars = get_ai_config().memory_max_chars
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
