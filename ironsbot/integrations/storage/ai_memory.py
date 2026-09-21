"""Platform-neutral persistence for principal-owned AI conversation memory."""

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
from ironsbot.services.identity_principals import default_actor_principal

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.core.platform import ActorPrincipal, ActorRef, ConversationRef
    from ironsbot.services.ai.history import HistoryMessage
    from ironsbot.services.ai.memory import AiMemoryTurn


_LOGGER = logging.getLogger(__name__)
_LEGACY_SCHEMA = (
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
_PRINCIPAL_SCHEMA = """
CREATE TABLE messages_v3 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    principal_kind TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    session_key TEXT NOT NULL,
    conversation_platform TEXT NOT NULL,
    conversation_account_id TEXT NOT NULL DEFAULT '',
    conversation_kind TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
)
"""
_MIGRATIONS = (
    SqliteMigration(1, _LEGACY_SCHEMA),
    SqliteMigration(
        2,
        callback=require_sqlite_columns(
            "messages",
            {"actor_account_id", "conversation_account_id"},
        ),
    ),
    SqliteMigration(
        3,
        callback=lambda connection: _migrate_to_principals(connection),  # noqa: PLW0108
    ),
)
MIGRATION_NAMESPACE = "ai_memory"


class SqliteAiMemoryStore:
    def __init__(
        self,
        path: str | Path,
        *,
        principal_for: Callable[[ActorRef], ActorPrincipal] = default_actor_principal,
    ) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )
        self._principal_for = principal_for

    async def append(self, turn: AiMemoryTurn) -> None:
        await asyncio.to_thread(self._append, turn)

    def _append(self, turn: AiMemoryTurn) -> None:
        now = time.time()
        identity = (
            *_principal_values(self._principal_for(turn.actor)),
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
                        principal_kind, principal_id, session_key,
                        conversation_platform, conversation_account_id,
                        conversation_kind, conversation_id,
                        role, content, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        WHERE principal_kind = ? AND principal_id = ?
        """
        params: list[object] = list(
            _principal_values(self._principal_for(actor))
        )
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

    def merge_principals(
        self,
        source: ActorPrincipal,
        target: ActorPrincipal,
    ) -> None:
        if source == target:
            return
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE messages SET principal_kind = ?, principal_id = ?
                WHERE principal_kind = ? AND principal_id = ?
                """,
                (*_principal_values(target), *_principal_values(source)),
            )


def _migrate_to_principals(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(messages)").fetchall()
    }
    if "principal_kind" in columns:
        return
    connection.execute("DROP INDEX IF EXISTS idx_ai_memory_actor_time")
    connection.execute(_PRINCIPAL_SCHEMA)
    rows = connection.execute(
        """
        SELECT id, actor_platform, actor_account_id, actor_kind,
               actor_id, actor_scope_id, session_key,
               conversation_platform, conversation_account_id,
               conversation_kind, conversation_id, role, content, created_at
        FROM messages
        """
    ).fetchall()
    for row in rows:
        actor = ActorIdentityColumns(
            str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5])
        ).to_actor()
        principal = default_actor_principal(actor)
        connection.execute(
            """
            INSERT INTO messages_v3 (
                id, principal_kind, principal_id, session_key,
                conversation_platform, conversation_account_id,
                conversation_kind, conversation_id,
                role, content, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row[0], *_principal_values(principal), *row[6:]),
        )
    connection.execute("DROP TABLE messages")
    connection.execute("ALTER TABLE messages_v3 RENAME TO messages")
    connection.execute(
        """
        CREATE INDEX idx_ai_memory_principal_time
        ON messages (principal_kind, principal_id, created_at DESC)
        """
    )


def _principal_values(principal: ActorPrincipal) -> tuple[str, str]:
    return principal.kind, principal.id


def _conversation_values(conversation: ConversationRef) -> tuple[str, str, str, str]:
    return ConversationIdentityColumns.from_conversation(conversation).values()
