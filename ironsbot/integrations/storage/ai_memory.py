"""Platform-neutral persistence for short AI conversation memory."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from typing import TYPE_CHECKING

from ironsbot.core.platform import reference_digest
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    require_sqlite_columns,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.ai.history import HistoryMessage
    from ironsbot.services.ai.memory import AiMemoryTurn


_LOGGER = logging.getLogger(__name__)
_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_platform TEXT NOT NULL,
        actor_account_id TEXT NOT NULL DEFAULT '',
        actor_kind TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_scope_id TEXT NOT NULL DEFAULT '',
        session_key TEXT NOT NULL,
        conversation_platform TEXT NOT NULL,
        conversation_account_id TEXT NOT NULL DEFAULT '',
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
        actor_platform, actor_account_id, actor_kind, actor_id, actor_scope_id,
        created_at DESC
    )
    """,
)
_MIGRATIONS = (
    SqliteMigration(1, _SCHEMA),
    SqliteMigration(
        2,
        callback=require_sqlite_columns(
            "messages",
            {"actor_account_id", "conversation_account_id"},
        ),
    ),
)
MIGRATION_NAMESPACE = "ai_memory"


class SqliteAiMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    async def append(self, turn: AiMemoryTurn) -> None:
        await asyncio.to_thread(self._append, turn)

    def _append(self, turn: AiMemoryTurn) -> None:
        now = time.time()
        identity = (
            *_actor_values(turn.actor),
            turn.session_key,
            *_conversation_values(turn.conversation),
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
                        actor_platform, actor_account_id, actor_kind, actor_id,
                        actor_scope_id,
                        session_key,
                        conversation_platform, conversation_account_id,
                        conversation_kind, conversation_id,
                        role, content, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        except sqlite3.Error:
            _LOGGER.warning(
                "failed to write AI memory platform=%s actor=%s",
                turn.actor.platform.value,
                reference_digest(turn.actor.id),
            )

    async def load(
        self,
        *,
        actor: ActorRef,
        current_session_key: str,
        exclude_current_session: bool,
        limit: int,
    ) -> list[HistoryMessage]:
        return await asyncio.to_thread(
            self._load,
            actor=actor,
            current_session_key=current_session_key,
            exclude_current_session=exclude_current_session,
            limit=limit,
        )

    def _load(
        self,
        *,
        actor: ActorRef,
        current_session_key: str,
        exclude_current_session: bool,
        limit: int,
    ) -> list[HistoryMessage]:
        sql = """
        SELECT role, content FROM messages
        WHERE actor_platform = ? AND actor_account_id = ?
          AND actor_kind = ? AND actor_id = ? AND actor_scope_id = ?
        """
        params: list[object] = list(_actor_values(actor))
        if exclude_current_session:
            sql += "AND session_key != ? "
            params.append(current_session_key)
        sql += "ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        try:
            with self._database.connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error:
            _LOGGER.warning(
                "failed to read AI memory platform=%s actor=%s",
                actor.platform.value,
                reference_digest(actor.id),
            )
            return []
        return [
            {"role": str(role), "content": str(content)}
            for role, content in reversed(rows)
        ]


def _actor_values(actor: ActorRef) -> tuple[str, str, str, str, str]:
    return ActorIdentityColumns.from_actor(actor).values()


def _conversation_values(conversation: ConversationRef) -> tuple[str, str, str, str]:
    return ConversationIdentityColumns.from_conversation(conversation).values()
