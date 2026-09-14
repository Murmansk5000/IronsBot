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
from ironsbot.services.seer.player_binding import PlayerBindingState

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.platform import ActorRef

_SCHEMA = """
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
_MIGRATIONS = (
    SqliteMigration(1, (_SCHEMA,)),
    SqliteMigration(
        2,
        callback=require_sqlite_columns("player_bindings", {"actor_account_id"}),
    ),
)
MIGRATION_NAMESPACE = "player_bindings"


class SqlitePlayerBindingStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def get(self, actor: ActorRef) -> PlayerBindingState:
        identity = ActorIdentityColumns.from_actor(actor)
        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT player_id, player_nick, choice_completed, last_changed_at
                FROM player_bindings
                WHERE actor_platform = ? AND actor_account_id = ?
                  AND actor_kind = ? AND actor_id = ? AND actor_scope_id = ?
                """,
                identity.values(),
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

    def bind(
        self,
        *,
        actor: ActorRef,
        player_id: int,
        player_nick: str,
        changed_at: datetime | None = None,
    ) -> None:
        now = _utc_now(changed_at)
        identity = ActorIdentityColumns.from_actor(actor)
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO player_bindings(
                    actor_platform, actor_account_id, actor_kind, actor_id,
                    actor_scope_id,
                    player_id, player_nick,
                    choice_completed, last_changed_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(
                    actor_platform, actor_account_id, actor_kind, actor_id,
                    actor_scope_id
                )
                DO UPDATE SET
                    player_id = excluded.player_id,
                    player_nick = excluded.player_nick,
                    choice_completed = 1,
                    last_changed_at = excluded.last_changed_at,
                    updated_at = excluded.updated_at
                WHERE player_bindings.player_id IS NOT excluded.player_id
                """,
                (*identity.values(), player_id, player_nick, now, now, now),
            )
    def decline(self, *, actor: ActorRef) -> None:
        now = _utc_now()
        identity = ActorIdentityColumns.from_actor(actor)
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO player_bindings(
                    actor_platform, actor_account_id, actor_kind, actor_id,
                    actor_scope_id,
                    player_id, player_nick,
                    choice_completed, last_changed_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, '', 1, NULL, ?, ?)
                ON CONFLICT(
                    actor_platform, actor_account_id, actor_kind, actor_id,
                    actor_scope_id
                )
                DO UPDATE SET
                    choice_completed = 1,
                    updated_at = excluded.updated_at
                """,
                (*identity.values(), now, now),
            )

    def unbind(
        self,
        *,
        actor: ActorRef,
        changed_at: datetime | None = None,
    ) -> bool:
        now = _utc_now(changed_at)
        identity = ActorIdentityColumns.from_actor(actor)
        with self._database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE player_bindings
                SET player_id = NULL, player_nick = '',
                    choice_completed = 1, last_changed_at = ?, updated_at = ?
                WHERE actor_platform = ? AND actor_account_id = ?
                  AND actor_kind = ? AND actor_id = ? AND actor_scope_id = ?
                  AND player_id IS NOT NULL
                """,
                (now, now, *identity.values()),
            )
            return cursor.rowcount > 0


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
