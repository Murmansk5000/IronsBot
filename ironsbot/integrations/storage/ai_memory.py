"""Platform-neutral persistence for short AI conversation memory."""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.ai.history import HistoryMessage
    from ironsbot.services.ai.memory import AiMemoryTurn


_LOGGER = logging.getLogger(__name__)
_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_platform TEXT NOT NULL,
        actor_kind TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_scope_id TEXT NOT NULL DEFAULT '',
        session_key TEXT NOT NULL,
        conversation_platform TEXT NOT NULL,
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_memory_actor_time
    ON messages (
        actor_platform, actor_kind, actor_id, actor_scope_id, created_at DESC
    )
    """,
)
_MIGRATIONS = (SqliteMigration(1, _SCHEMA),)
MIGRATION_NAMESPACE = "ai_memory"


class SqliteAiMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def append(self, turn: AiMemoryTurn) -> None:
        now = time.time()
        actor = _onebot_actor(turn.user_id)
        conversation = _conversation_for_turn(turn)
        identity = (
            *_actor_values(actor),
            turn.session_key,
            *_conversation_values(conversation),
        )
        rows = (
            (*identity, "user", turn.prompt, now),
            (*identity, "assistant", turn.reply, now + 0.001),
        )
        try:
            with self._database.connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO messages (
                        actor_platform, actor_kind, actor_id, actor_scope_id,
                        session_key,
                        conversation_platform, conversation_kind, conversation_id,
                        role, content, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
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
        sql = """
        SELECT role, content FROM messages
        WHERE actor_platform = ? AND actor_kind = ? AND actor_id = ?
          AND actor_scope_id = ?
        """
        params: list[object] = list(_actor_values(_onebot_actor(user_id)))
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


def _onebot_actor(user_id: int) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(int(user_id)))


def _conversation_for_turn(turn: AiMemoryTurn) -> ConversationRef:
    kind = "group" if turn.chat_scope == "group" else "private"
    return ConversationRef(Platform.ONEBOT, kind, str(int(turn.chat_id)))


def _actor_values(actor: ActorRef) -> tuple[str, str, str, str]:
    return ActorIdentityColumns.from_actor(actor).values()


def _conversation_values(conversation: ConversationRef) -> tuple[str, str, str]:
    return ConversationIdentityColumns.from_conversation(conversation).values()
