# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.seer.player_binding import PlayerBindingState

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_bindings (
    qq_user_id INTEGER PRIMARY KEY,
    player_id INTEGER,
    player_nick TEXT,
    choice_completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""
_MIGRATIONS = (SqliteMigration(1, (_SCHEMA,)),)


class SqlitePlayerBindingStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(path, migrations=_MIGRATIONS)

    def get(self, qq_user_id: int) -> PlayerBindingState:
        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT player_id, player_nick, choice_completed
                FROM player_bindings
                WHERE qq_user_id = ?
                """,
                (qq_user_id,),
            ).fetchone()
        if row is None:
            return PlayerBindingState(qq_user_id)
        return PlayerBindingState(
            qq_user_id,
            None if row[0] is None else int(row[0]),
            str(row[1] or ""),
            bool(row[2]),
        )

    def bind(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        player_nick: str,
    ) -> None:
        now = _utc_now()
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO player_bindings(
                    qq_user_id, player_id, player_nick,
                    choice_completed, created_at, updated_at
                )
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(qq_user_id) DO UPDATE SET
                    player_id = excluded.player_id,
                    player_nick = excluded.player_nick,
                    choice_completed = 1,
                    updated_at = excluded.updated_at
                """,
                (qq_user_id, player_id, player_nick, now, now),
            )

    def decline(self, *, qq_user_id: int) -> None:
        now = _utc_now()
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO player_bindings(
                    qq_user_id, player_id, player_nick,
                    choice_completed, created_at, updated_at
                )
                VALUES (?, NULL, '', 1, ?, ?)
                ON CONFLICT(qq_user_id) DO UPDATE SET
                    choice_completed = 1,
                    updated_at = excluded.updated_at
                """,
                (qq_user_id, now, now),
            )

    def unbind(self, *, qq_user_id: int) -> bool:
        with self._database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE player_bindings
                SET player_id = NULL, player_nick = '',
                    choice_completed = 1, updated_at = ?
                WHERE qq_user_id = ? AND player_id IS NOT NULL
                """,
                (_utc_now(), qq_user_id),
            )
            return cursor.rowcount > 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
