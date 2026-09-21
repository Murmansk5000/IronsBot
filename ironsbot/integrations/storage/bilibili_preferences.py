# SPDX-License-Identifier: MIT
"""Conversation-scoped Bilibili push preferences."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.conversation_principal_rows import (
    PrincipalRowMergeSpec,
    PrincipalTableCopySpec,
    copy_conversation_rows_to_principals,
    merge_latest_principal_rows,
)
from ironsbot.integrations.storage.platform_identity import (
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    require_sqlite_columns,
)
from ironsbot.services.identity_principals import default_conversation_principal

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.core.platform import ConversationPrincipal, ConversationRef
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
_PRINCIPAL_TABLES = (
    """
    CREATE TABLE bili_push_preferences_v4 (
        principal_kind TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        conversation_platform TEXT NOT NULL,
        conversation_account_id TEXT NOT NULL DEFAULT '',
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        uid INTEGER NOT NULL,
        mode TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (principal_kind, principal_id, uid)
    )
    """,
    """
    CREATE TABLE bili_push_category_preferences_v4 (
        principal_kind TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        conversation_platform TEXT NOT NULL,
        conversation_account_id TEXT NOT NULL DEFAULT '',
        conversation_kind TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        uid INTEGER NOT NULL,
        category TEXT NOT NULL,
        muted INTEGER NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (principal_kind, principal_id, uid, category)
    )
    """,
)
_PRINCIPAL_INDEX = """
    CREATE INDEX idx_bili_push_preferences_uid
    ON bili_push_preferences (uid, principal_kind, principal_id)
"""
_MODE_MERGE = PrincipalRowMergeSpec(
    table="bili_push_preferences",
    value_columns=(
        "conversation_platform",
        "conversation_account_id",
        "conversation_kind",
        "conversation_id",
        "uid",
        "mode",
        "updated_at",
    ),
    identity_columns=("uid",),
    order_columns=("updated_at",),
)
_CATEGORY_MERGE = PrincipalRowMergeSpec(
    table="bili_push_category_preferences",
    value_columns=(
        "conversation_platform",
        "conversation_account_id",
        "conversation_kind",
        "conversation_id",
        "uid",
        "category",
        "muted",
        "updated_at",
    ),
    identity_columns=("uid", "category"),
    order_columns=("updated_at",),
)


def _migrate_bili_principals(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(bili_push_preferences)"
        ).fetchall()
    }
    if "principal_kind" in columns:
        return
    for statement in _PRINCIPAL_TABLES:
        connection.execute(statement)
    copy_conversation_rows_to_principals(
        connection,
        PrincipalTableCopySpec(
            "bili_push_preferences",
            "bili_push_preferences_v4",
            ("uid", "mode", "updated_at"),
        ),
    )
    copy_conversation_rows_to_principals(
        connection,
        PrincipalTableCopySpec(
            "bili_push_category_preferences",
            "bili_push_category_preferences_v4",
            ("uid", "category", "muted", "updated_at"),
        ),
    )
    for table in ("bili_push_preferences", "bili_push_category_preferences"):
        connection.execute(f"DROP TABLE {table}")
        connection.execute(f"ALTER TABLE {table}_v4 RENAME TO {table}")
    connection.execute(_PRINCIPAL_INDEX)


def _split_lottery_and_winning_preferences(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO bili_push_category_preferences (
            principal_kind, principal_id,
            conversation_platform, conversation_account_id,
            conversation_kind, conversation_id,
            uid, category, muted, updated_at
        )
        SELECT lottery.principal_kind, lottery.principal_id,
               lottery.conversation_platform, lottery.conversation_account_id,
               lottery.conversation_kind, lottery.conversation_id,
               lottery.uid, 'winning', lottery.muted, lottery.updated_at
        FROM bili_push_category_preferences AS lottery
        WHERE lottery.category = 'lottery'
          AND NOT EXISTS (
              SELECT 1
              FROM bili_push_category_preferences AS winning
              WHERE winning.principal_kind = lottery.principal_kind
                AND winning.principal_id = lottery.principal_id
                AND winning.uid = lottery.uid
                AND winning.category = 'winning'
          )
        """
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
    SqliteMigration(4, callback=_migrate_bili_principals),
    SqliteMigration(5, callback=_split_lottery_and_winning_preferences),
)
MIGRATION_NAMESPACE = "bilibili_preferences"


class SqliteBiliPushPreferenceStore:
    """Persist Bilibili push modes by opaque conversation identity."""

    def __init__(
        self,
        path: str | Path,
        *,
        principal_for: Callable[
            [ConversationRef], ConversationPrincipal
        ] = default_conversation_principal,
    ) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )
        self._principal_for = principal_for

    def get_mode(
        self,
        conversation: ConversationRef,
        uid: int,
    ) -> BiliRuntimePushMode | None:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT mode FROM bili_push_preferences
                WHERE principal_kind = ? AND principal_id = ? AND uid = ?
                """,
                (*self._owner_values(conversation), uid),
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
                    principal_kind, principal_id,
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id,
                    uid, mode, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    *self._owner_values(conversation),
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
                WHERE principal_kind = ? AND principal_id = ? AND uid = ?
                """,
                (*self._owner_values(conversation), uid),
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
                WHERE principal_kind = ? AND principal_id = ?
                  AND uid = ? AND category = ?
                """,
                (*self._owner_values(conversation), uid, category),
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
                    principal_kind, principal_id,
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id,
                    uid, category, muted, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(
                    principal_kind, principal_id, uid, category
                ) DO UPDATE SET muted = excluded.muted, updated_at = excluded.updated_at
                """,
                (
                    *self._owner_values(conversation),
                    *_conversation_values(conversation),
                    uid,
                    category,
                    int(muted),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def merge_principals(
        self,
        source: ConversationPrincipal,
        target: ConversationPrincipal,
    ) -> None:
        if source == target:
            return
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            merge_latest_principal_rows(
                connection,
                _MODE_MERGE,
                source=source,
                target=target,
            )
            merge_latest_principal_rows(
                connection,
                _CATEGORY_MERGE,
                source=source,
                target=target,
            )

    def _owner_values(self, conversation: ConversationRef) -> tuple[str, str]:
        principal = self._principal_for(conversation)
        return principal.kind, principal.id


def _conversation_values(conversation: ConversationRef) -> tuple[str, str, str, str]:
    return ConversationIdentityColumns.from_conversation(conversation).values()
