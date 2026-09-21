# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-conversation rank display preferences."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.conversation_principal_rows import (
    PrincipalRowMergeSpec,
    PrincipalTableCopySpec,
    copy_conversation_rows_to_principals,
    merge_latest_principal_rows,
)
from ironsbot.integrations.storage.platform_identity import (
    ActorIdentityColumns,
    ConversationIdentityColumns,
)
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    require_sqlite_columns,
)
from ironsbot.services.identity_principals import default_conversation_principal

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.core.platform import (
        ActorRef,
        ConversationPrincipal,
        ConversationRef,
    )


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
_PRINCIPAL_SCHEMA = """
CREATE TABLE group_rank_display_limits_v3 (
    principal_kind TEXT NOT NULL,
    principal_id TEXT NOT NULL,
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
    PRIMARY KEY (principal_kind, principal_id)
)
"""
_MERGE_SPEC = PrincipalRowMergeSpec(
    table="group_rank_display_limits",
    value_columns=(
        "conversation_platform",
        "conversation_account_id",
        "conversation_kind",
        "conversation_id",
        "display_limit",
        "updated_at",
        "updated_by_platform",
        "updated_by_account_id",
        "updated_by_kind",
        "updated_by_id",
        "updated_by_scope_id",
    ),
    identity_columns=(),
    order_columns=("updated_at",),
)


def _migrate_rank_display_principals(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(group_rank_display_limits)"
        ).fetchall()
    }
    if "principal_kind" in columns:
        return
    connection.execute(_PRINCIPAL_SCHEMA)
    copy_conversation_rows_to_principals(
        connection,
        PrincipalTableCopySpec(
            "group_rank_display_limits",
            "group_rank_display_limits_v3",
            (
                "display_limit",
                "updated_at",
                "updated_by_platform",
                "updated_by_account_id",
                "updated_by_kind",
                "updated_by_id",
                "updated_by_scope_id",
            ),
        ),
    )
    connection.execute("DROP TABLE group_rank_display_limits")
    connection.execute(
        "ALTER TABLE group_rank_display_limits_v3 "
        "RENAME TO group_rank_display_limits"
    )


_MIGRATIONS = (
    SqliteMigration(1, (_SCHEMA,)),
    SqliteMigration(
        2,
        callback=require_sqlite_columns(
            "group_rank_display_limits",
            {"conversation_account_id", "updated_by_account_id"},
        ),
    ),
    SqliteMigration(3, callback=_migrate_rank_display_principals),
)
MIGRATION_NAMESPACE = "rank_display"


class SqliteRankDisplayStore:
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

    def get(self, conversation: ConversationRef) -> int | None:
        try:
            with self._database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT display_limit FROM group_rank_display_limits
                    WHERE principal_kind = ? AND principal_id = ?
                    """,
                    self._owner_values(conversation),
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
                    principal_kind, principal_id,
                    conversation_platform, conversation_account_id,
                    conversation_kind, conversation_id,
                    display_limit, updated_at,
                    updated_by_platform, updated_by_account_id, updated_by_kind,
                    updated_by_id, updated_by_scope_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(principal_kind, principal_id)
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
                    *self._owner_values(conversation),
                    *ConversationIdentityColumns.from_conversation(
                        conversation
                    ).values(),
                    limit,
                    datetime.now(timezone.utc).isoformat(),
                    *ActorIdentityColumns.from_actor(actor).values(),
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
                _MERGE_SPEC,
                source=source,
                target=target,
            )

    def _owner_values(self, conversation: ConversationRef) -> tuple[str, str]:
        principal = self._principal_for(conversation)
        return principal.kind, principal.id
