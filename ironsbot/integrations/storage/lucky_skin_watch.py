# SPDX-License-Identifier: MIT
"""Principal-owned lucky-skin watch preferences."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.platform_identity import ActorIdentityColumns
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    require_sqlite_columns,
)
from ironsbot.services.identity_principals import default_actor_principal

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.core.platform import ActorPrincipal, ActorRef


_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS lucky_skin_watch_preferences (
    actor_platform TEXT NOT NULL,
    actor_account_id TEXT NOT NULL DEFAULT '',
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_scope_id TEXT NOT NULL DEFAULT '',
    skin_ids_json TEXT NOT NULL,
    initialized_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (
        actor_platform, actor_account_id, actor_kind, actor_id, actor_scope_id
    )
)
"""
_PRINCIPAL_SCHEMA = """
CREATE TABLE lucky_skin_watch_preferences_v3 (
    principal_kind TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    skin_ids_json TEXT NOT NULL,
    initialized_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (principal_kind, principal_id)
)
"""
_MIGRATIONS = (
    SqliteMigration(1, (_LEGACY_SCHEMA,)),
    SqliteMigration(
        2,
        callback=require_sqlite_columns(
            "lucky_skin_watch_preferences",
            {"actor_account_id"},
        ),
    ),
    SqliteMigration(
        3,
        callback=lambda connection: _migrate_to_principals(connection),  # noqa: PLW0108
    ),
)
MIGRATION_NAMESPACE = "lucky_skin_watch"


class SqliteLuckySkinWatchPreferenceStore:
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

    def get(self, actor: ActorRef) -> tuple[int, ...] | None:
        principal = self._principal_for(actor)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT skin_ids_json FROM lucky_skin_watch_preferences
                WHERE principal_kind = ? AND principal_id = ?
                """,
                _principal_values(principal),
            ).fetchone()
        return None if row is None else _decode_skin_ids(row[0])

    def set(self, actor: ActorRef, skin_ids: tuple[int, ...]) -> None:
        principal = self._principal_for(actor)
        normalized = _normalize_skin_ids(skin_ids)
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(normalized, separators=(",", ":"))
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO lucky_skin_watch_preferences (
                    principal_kind, principal_id,
                    skin_ids_json, initialized_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(principal_kind, principal_id) DO UPDATE SET
                    skin_ids_json = excluded.skin_ids_json,
                    updated_at = excluded.updated_at
                """,
                (*_principal_values(principal), payload, now, now),
            )

    def merge_principals(
        self,
        source: ActorPrincipal,
        target: ActorPrincipal,
    ) -> None:
        if source == target:
            return
        with self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source_row = _preference_row(connection, source)
            target_row = _preference_row(connection, target)
            selected = _newest_preference(source_row, target_row)
            if selected is not None:
                connection.execute(
                    """
                    INSERT INTO lucky_skin_watch_preferences (
                        principal_kind, principal_id,
                        skin_ids_json, initialized_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(principal_kind, principal_id) DO UPDATE SET
                        skin_ids_json = excluded.skin_ids_json,
                        initialized_at = excluded.initialized_at,
                        updated_at = excluded.updated_at
                    """,
                    (*_principal_values(target), *selected),
                )
            connection.execute(
                "DELETE FROM lucky_skin_watch_preferences "
                "WHERE principal_kind = ? AND principal_id = ?",
                _principal_values(source),
            )


def _migrate_to_principals(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(lucky_skin_watch_preferences)"
        ).fetchall()
    }
    if "principal_kind" in columns:
        return
    connection.execute(_PRINCIPAL_SCHEMA)
    rows = connection.execute(
        """
        SELECT actor_platform, actor_account_id, actor_kind, actor_id,
               actor_scope_id, skin_ids_json, initialized_at, updated_at
        FROM lucky_skin_watch_preferences
        """
    ).fetchall()
    for row in rows:
        actor = ActorIdentityColumns(
            str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4])
        ).to_actor()
        principal = default_actor_principal(actor)
        connection.execute(
            """
            INSERT INTO lucky_skin_watch_preferences_v3 (
                principal_kind, principal_id,
                skin_ids_json, initialized_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (*_principal_values(principal), *row[5:]),
        )
    connection.execute("DROP TABLE lucky_skin_watch_preferences")
    connection.execute(
        "ALTER TABLE lucky_skin_watch_preferences_v3 "
        "RENAME TO lucky_skin_watch_preferences"
    )


def _preference_row(
    connection: sqlite3.Connection,
    principal: ActorPrincipal,
) -> tuple[object, ...] | None:
    return connection.execute(
        """
        SELECT skin_ids_json, initialized_at, updated_at
        FROM lucky_skin_watch_preferences
        WHERE principal_kind = ? AND principal_id = ?
        """,
        _principal_values(principal),
    ).fetchone()


def _newest_preference(
    first: tuple[object, ...] | None,
    second: tuple[object, ...] | None,
) -> tuple[object, ...] | None:
    if first is None:
        return second
    if second is None:
        return first
    return max((first, second), key=lambda row: str(row[2]))


def _principal_values(principal: ActorPrincipal) -> tuple[str, str]:
    return principal.kind, principal.id


def _decode_skin_ids(value: object) -> tuple[int, ...]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(decoded, list):
        return ()
    try:
        return _normalize_skin_ids(tuple(int(item) for item in decoded))
    except (TypeError, ValueError):
        return ()


def _normalize_skin_ids(skin_ids: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(skin_id for skin_id in skin_ids if skin_id > 0))
