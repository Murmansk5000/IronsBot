# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.platform_identity import ActorIdentityColumns
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    require_sqlite_columns,
)
from ironsbot.services.identity_principals import default_actor_principal
from ironsbot.services.seer.player_binding import PlayerBindingState

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.core.platform import ActorPrincipal, ActorRef

_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_bindings (
    actor_platform TEXT NOT NULL,
    actor_account_id TEXT NOT NULL DEFAULT '',
    actor_kind TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_scope_id TEXT NOT NULL DEFAULT '',
    player_id INTEGER,
    player_nick TEXT,
    choice_completed INTEGER NOT NULL DEFAULT 0,
    last_changed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (
        actor_platform, actor_account_id, actor_kind, actor_id, actor_scope_id
    )
)
"""
_PRINCIPAL_SCHEMA = """
CREATE TABLE player_bindings_v3 (
    principal_kind TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    player_id INTEGER,
    player_nick TEXT,
    choice_completed INTEGER NOT NULL DEFAULT 0,
    last_changed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (principal_kind, principal_id)
)
"""
_MIGRATIONS = (
    SqliteMigration(1, (_LEGACY_SCHEMA,)),
    SqliteMigration(
        2,
        callback=require_sqlite_columns("player_bindings", {"actor_account_id"}),
    ),
    SqliteMigration(
        3,
        callback=lambda connection: _migrate_to_principals(connection),  # noqa: PLW0108
    ),
)
MIGRATION_NAMESPACE = "player_bindings"


class SqlitePlayerBindingStore:
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

    def get(self, actor: ActorRef) -> PlayerBindingState:
        principal = self._principal_for(actor)
        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT player_id, player_nick, choice_completed, last_changed_at
                FROM player_bindings
                WHERE principal_kind = ? AND principal_id = ?
                """,
                _principal_values(principal),
            ).fetchone()
        if row is None:
            return PlayerBindingState(actor)
        return PlayerBindingState(
            actor,
            None if row[0] is None else int(row[0]),
            str(row[1] or ""),
            bool(row[2]),
            _parse_datetime(row[3]),
        )

    def merge_principals(
        self,
        source: ActorPrincipal,
        target: ActorPrincipal,
    ) -> None:
        """Move one obsolete owner into its selected principal atomically."""

        if source == target:
            return
        with self._database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            source_row = _binding_row(conn, source)
            target_row = _binding_row(conn, target)
            if source_row is not None and (
                target_row is None
                or (target_row[0] is None and source_row[0] is not None)
            ):
                conn.execute(
                    """
                    INSERT INTO player_bindings (
                        principal_kind, principal_id, player_id, player_nick,
                        choice_completed, last_changed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (principal_kind, principal_id) DO UPDATE SET
                        player_id = excluded.player_id,
                        player_nick = excluded.player_nick,
                        choice_completed = excluded.choice_completed,
                        last_changed_at = excluded.last_changed_at,
                        updated_at = excluded.updated_at
                    """,
                    (*_principal_values(target), *source_row),
                )
            conn.execute(
                "DELETE FROM player_bindings "
                "WHERE principal_kind = ? AND principal_id = ?",
                _principal_values(source),
            )

    def bind(
        self,
        *,
        actor: ActorRef,
        player_id: int,
        player_nick: str,
        changed_at: datetime | None = None,
    ) -> None:
        now = _utc_now(changed_at)
        principal = self._principal_for(actor)
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO player_bindings(
                    principal_kind, principal_id, player_id, player_nick,
                    choice_completed, last_changed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(principal_kind, principal_id) DO UPDATE SET
                    player_id = excluded.player_id,
                    player_nick = excluded.player_nick,
                    choice_completed = 1,
                    last_changed_at = excluded.last_changed_at,
                    updated_at = excluded.updated_at
                WHERE player_bindings.player_id IS NOT excluded.player_id
                """,
                (*_principal_values(principal), player_id, player_nick, now, now, now),
            )

    def decline(self, *, actor: ActorRef) -> None:
        now = _utc_now()
        principal = self._principal_for(actor)
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO player_bindings(
                    principal_kind, principal_id, player_id, player_nick,
                    choice_completed, last_changed_at, created_at, updated_at
                ) VALUES (?, ?, NULL, '', 1, NULL, ?, ?)
                ON CONFLICT(principal_kind, principal_id) DO UPDATE SET
                    choice_completed = 1,
                    updated_at = excluded.updated_at
                """,
                (*_principal_values(principal), now, now),
            )

    def unbind(
        self,
        *,
        actor: ActorRef,
        changed_at: datetime | None = None,
    ) -> bool:
        now = _utc_now(changed_at)
        principal = self._principal_for(actor)
        with self._database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE player_bindings
                SET player_id = NULL, player_nick = '',
                    choice_completed = 1, last_changed_at = ?, updated_at = ?
                WHERE principal_kind = ? AND principal_id = ?
                  AND player_id IS NOT NULL
                """,
                (now, now, *_principal_values(principal)),
            )
            return cursor.rowcount > 0


def _migrate_to_principals(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(player_bindings)").fetchall()
    }
    if "principal_kind" in columns:
        return
    connection.execute(_PRINCIPAL_SCHEMA)
    rows = connection.execute(
        """
        SELECT actor_platform, actor_account_id, actor_kind, actor_id,
               actor_scope_id, player_id, player_nick, choice_completed,
               last_changed_at, created_at, updated_at
        FROM player_bindings
        """
    ).fetchall()
    for row in rows:
        actor = ActorIdentityColumns(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
        ).to_actor()
        principal = default_actor_principal(actor)
        connection.execute(
            """
            INSERT INTO player_bindings_v3 (
                principal_kind, principal_id, player_id, player_nick,
                choice_completed, last_changed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*_principal_values(principal), *row[5:]),
        )
    connection.execute("DROP TABLE player_bindings")
    connection.execute("ALTER TABLE player_bindings_v3 RENAME TO player_bindings")


def _binding_row(
    connection: sqlite3.Connection,
    principal: ActorPrincipal,
) -> tuple[object, ...] | None:
    return connection.execute(
        """
        SELECT player_id, player_nick, choice_completed, last_changed_at,
               created_at, updated_at
        FROM player_bindings
        WHERE principal_kind = ? AND principal_id = ?
        """,
        _principal_values(principal),
    ).fetchone()


def _principal_values(principal: ActorPrincipal) -> tuple[str, str]:
    return principal.kind, principal.id


def _utc_now(value: datetime | None = None) -> str:
    current = datetime.now(timezone.utc) if value is None else value
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
