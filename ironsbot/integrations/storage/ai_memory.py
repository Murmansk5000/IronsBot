from __future__ import annotations

import logging
import sqlite3
import time
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.ai.history import HistoryMessage
    from ironsbot.services.ai.memory import AiMemoryTurn

_LOGGER = logging.getLogger(__name__)
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS messages ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "user_id INTEGER NOT NULL, session_key TEXT NOT NULL, "
    "chat_scope TEXT NOT NULL, chat_id INTEGER NOT NULL, "
    "role TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL"
    ")",
    "CREATE INDEX IF NOT EXISTS idx_ai_memory_user_time "
    "ON messages (user_id, created_at DESC)",
)
_MIGRATIONS = (SqliteMigration(1, _SCHEMA),)


class SqliteAiMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(path, migrations=_MIGRATIONS)

    def append(self, turn: AiMemoryTurn) -> None:
        now = time.time()
        identity = (
            turn.user_id,
            turn.session_key,
            turn.chat_scope,
            turn.chat_id,
        )
        rows = (
            (*identity, "user", turn.prompt, now),
            (*identity, "assistant", turn.reply, now + 0.001),
        )
        try:
            with self._database.connect() as conn:
                conn.executemany(
                    "INSERT INTO messages ("
                    "user_id, session_key, chat_scope, chat_id, "
                    "role, content, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
        except sqlite3.Error:
            _LOGGER.warning("failed to write AI memory for %s", turn.user_id)

    def load(
        self,
        *,
        user_id: int,
        current_session_key: str,
        exclude_current_session: bool,
        limit: int,
    ) -> list[HistoryMessage]:
        sql = "SELECT role, content FROM messages WHERE user_id = ? "
        params: list[object] = [user_id]
        if exclude_current_session:
            sql += "AND session_key != ? "
            params.append(current_session_key)
        sql += "ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        try:
            with self._database.connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error:
            _LOGGER.warning("failed to read AI memory for %s", user_id)
            return []
        return [
            {"role": str(role), "content": str(content)}
            for role, content in reversed(rows)
        ]
