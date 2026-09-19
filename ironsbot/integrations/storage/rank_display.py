# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-conversation rank display preferences."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

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


_SCHEMA = """
CREATE TABLE IF NOT EXISTS group_rank_display_limits (
    conversation_platform TEXT NOT NULL,
    conversation_account_id TEXT NOT NULL DEFAULT '',
    conversation_kind TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    display_limit INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by_platform TEXT NOT NULL,
    updated_by_account_id TEXT NOT NULL DEFAULT '',
    updated_by_kind TEXT NOT NULL,
    updated_by_id TEXT NOT NULL,
    updated_by_scope_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (
        conversation_platform, conversation_account_id, conversation_kind,
        conversation_id
    )
)
"""
_MIGRATIONS = (
    SqliteMigration(1, (_SCHEMA,)),
    SqliteMigration(
        2,
        callback=require_sqlite_columns(
            "group_rank_display_limits",
            {"conversation_account_id", "updated_by_account_id"},
        ),
    ),
)
MIGRATION_NAMESPACE = "rank_display"


class SqliteRankDisplayStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def get(self, conversation: ConversationRef) -> int | None:
        try:
            with self._database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT display_limit FROM group_rank_display_limits
                    WHERE conversation_platform = ?
                      AND conversation_account_id = ?
                      AND conversation_kind = ? AND conversation_id = ?
                    """,
                    ConversationIdentityColumns.from_conversation(
                        conversation
                    ).values(),
                ).fetchone()
        except sqlite3.Error:
            return None
        return int(row[0]) if row is not None else None

    def set(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
        limit: int,
    ) -> None:
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO group_rank_display_limits (
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id,
                    display_limit, updated_at,
                    updated_by_platform, updated_by_account_id, updated_by_kind,
                    updated_by_id, updated_by_scope_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id
                )
                DO UPDATE SET
                    display_limit = excluded.display_limit,
                    updated_at = excluded.updated_at,
                    updated_by_platform = excluded.updated_by_platform,
                    updated_by_account_id = excluded.updated_by_account_id,
                    updated_by_kind = excluded.updated_by_kind,
                    updated_by_id = excluded.updated_by_id,
                    updated_by_scope_id = excluded.updated_by_scope_id
                """,
                (
                    *ConversationIdentityColumns.from_conversation(
                        conversation
                    ).values(),
                    limit,
                    datetime.now(timezone.utc).isoformat(),
                    *ActorIdentityColumns.from_actor(actor).values(),
                ),
            )
