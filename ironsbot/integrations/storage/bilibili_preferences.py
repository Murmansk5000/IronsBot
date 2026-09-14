# SPDX-License-Identifier: MIT
"""Conversation-scoped Bilibili push preferences."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.platform_identity import (
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    require_sqlite_columns,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.bilibili.preferences import BiliRuntimePushMode


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS bili_push_preferences (
        conversation_platform TEXT NOT NULL,
        conversation_account_id TEXT NOT NULL DEFAULT '',
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        uid INTEGER NOT NULL,
        mode TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (
            conversation_platform, conversation_account_id, conversation_kind,
            conversation_id, uid
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_bili_push_preferences_uid
    ON bili_push_preferences (
        uid, conversation_platform, conversation_account_id, conversation_kind,
        conversation_id
    )
    """,
)
_CATEGORY_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS bili_push_category_preferences (
        conversation_platform TEXT NOT NULL,
        conversation_account_id TEXT NOT NULL DEFAULT '',
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        uid INTEGER NOT NULL,
        category TEXT NOT NULL,
        muted INTEGER NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (
            conversation_platform, conversation_account_id, conversation_kind,
            conversation_id,
            uid, category
        )
    )
    """,
)
_MIGRATIONS = (
    SqliteMigration(1, _SCHEMA),
    SqliteMigration(2, _CATEGORY_SCHEMA),
    SqliteMigration(
        3,
        callback=require_sqlite_columns(
            "bili_push_preferences",
            {"conversation_account_id"},
        ),
    ),
    # The original lottery category covered both prize draws and results.
    # Preserve every target's existing choice when those become independent.
    SqliteMigration(
        4,
        (
            "INSERT OR IGNORE INTO bili_push_category_preferences "
            "(conversation_platform, conversation_account_id, "
            "conversation_kind, conversation_id, uid, category, muted, updated_at) "
            "SELECT conversation_platform, conversation_account_id, "
            "conversation_kind, conversation_id, uid, 'winning', muted, updated_at "
            "FROM bili_push_category_preferences WHERE category = 'lottery'",
        ),
    ),
)
MIGRATION_NAMESPACE = "bilibili_preferences"


class SqliteBiliPushPreferenceStore:
    """Persist Bilibili push modes by opaque conversation identity."""

    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def get_mode(
        self,
        conversation: ConversationRef,
        uid: int,
    ) -> BiliRuntimePushMode | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT mode FROM bili_push_preferences
                WHERE conversation_platform = ?
                  AND conversation_account_id = ?
                  AND conversation_kind = ? AND conversation_id = ? AND uid = ?
                """,
                (*_conversation_values(conversation), uid),
            ).fetchone()
        mode = str(row[0]) if row is not None else ""
        if mode == "full":
            return "full"
        if mode == "link":
            return "link"
        return None

    def set_mode(
        self,
        conversation: ConversationRef,
        uid: int,
        mode: BiliRuntimePushMode,
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO bili_push_preferences (
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id,
                    uid, mode, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    *_conversation_values(conversation),
                    uid,
                    mode,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def clear_mode(
        self,
        conversation: ConversationRef,
        uid: int,
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                DELETE FROM bili_push_preferences
                WHERE conversation_platform = ?
                  AND conversation_account_id = ?
                  AND conversation_kind = ? AND conversation_id = ? AND uid = ?
                """,
                (*_conversation_values(conversation), uid),
            )

    def category_muted(
        self,
        conversation: ConversationRef,
        uid: int,
        category: str,
    ) -> bool | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT muted FROM bili_push_category_preferences
                WHERE conversation_platform = ?
                  AND conversation_account_id = ?
                  AND conversation_kind = ? AND conversation_id = ?
                  AND uid = ? AND category = ?
                """,
                (*_conversation_values(conversation), uid, category),
            ).fetchone()
        return None if row is None else bool(row[0])

    def set_category_muted(
        self,
        conversation: ConversationRef,
        uid: int,
        category: str,
        *,
        muted: bool,
    ) -> None:
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO bili_push_category_preferences (
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id,
                    uid, category, muted, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id, uid, category
                ) DO UPDATE SET muted = excluded.muted, updated_at = excluded.updated_at
                """,
                (
                    *_conversation_values(conversation),
                    uid,
                    category,
                    int(muted),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


def _conversation_values(conversation: ConversationRef) -> tuple[str, str, str, str]:
    return ConversationIdentityColumns.from_conversation(conversation).values()
