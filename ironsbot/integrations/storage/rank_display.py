# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-conversation rank display preferences."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS group_rank_display_limits (
    conversation_platform TEXT NOT NULL,
    conversation_kind TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    display_limit INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by_platform TEXT NOT NULL,
    updated_by_kind TEXT NOT NULL,
    updated_by_id TEXT NOT NULL,
    updated_by_scope_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (conversation_platform, conversation_kind, conversation_id)
)
"""
_MIGRATIONS = (SqliteMigration(1, (_SCHEMA,)),)
MIGRATION_NAMESPACE = "rank_display"


class SqliteRankDisplayStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def get(self, group_id: int) -> int | None:
        try:
            with self._database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT display_limit FROM group_rank_display_limits
                    WHERE conversation_platform = ? AND conversation_kind = ?
                      AND conversation_id = ?
                    """,
                    _group_values(group_id),
                ).fetchone()
        except sqlite3.Error:
            return None
        return int(row[0]) if row is not None else None

    def set(self, group_id: int, user_id: int, limit: int) -> None:
        conversation = _group_conversation(group_id)
        actor = ActorRef(Platform.ONEBOT, str(int(user_id)))
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO group_rank_display_limits (
                    conversation_platform, conversation_kind, conversation_id,
                    display_limit, updated_at,
                    updated_by_platform, updated_by_kind, updated_by_id,
                    updated_by_scope_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_platform, conversation_kind, conversation_id)
                DO UPDATE SET
                    display_limit = excluded.display_limit,
                    updated_at = excluded.updated_at,
                    updated_by_platform = excluded.updated_by_platform,
                    updated_by_kind = excluded.updated_by_kind,
                    updated_by_id = excluded.updated_by_id,
                    updated_by_scope_id = excluded.updated_by_scope_id
                """,
                (
                    *ConversationIdentityColumns.from_conversation(conversation).values(),
                    limit,
                    datetime.now(timezone.utc).isoformat(),
                    *ActorIdentityColumns.from_actor(actor).values(),
                ),
            )


def _group_conversation(group_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(int(group_id)))


def _group_values(group_id: int) -> tuple[str, str, str]:
    return ConversationIdentityColumns.from_conversation(
        _group_conversation(group_id)
    ).values()
