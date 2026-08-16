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
_MIGRATIONS = (
    SqliteMigration(1, (_SCHEMA,)),
    SqliteMigration(
        2,
        (
            "ALTER TABLE player_bindings ADD COLUMN last_changed_at TEXT",
            """
            UPDATE player_bindings
            SET last_changed_at = updated_at
            WHERE player_id IS NOT NULL AND last_changed_at IS NULL
            """,
        ),
    ),
)
MIGRATION_NAMESPACE = "player_bindings"


class PlayerBindingWriteError(RuntimeError):
    """Raised when a binding write cannot be verified."""

    def __init__(
        self,
        *,
        expected_player_id: int,
        actual_player_id: int | None,
    ) -> None:
        super().__init__(
            "保存后的默认米米号与请求不一致："
            f"expected={expected_player_id} actual={actual_player_id}"
        )


class SqlitePlayerBindingStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def get(self, qq_user_id: int) -> PlayerBindingState:
        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT player_id, player_nick, choice_completed, last_changed_at
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
            _parse_datetime(row[3]),
        )

    def bind(
        self,
        *,
        qq_user_id: int,
        player_id: int,
        player_nick: str,
        changed_at: datetime | None = None,
    ) -> None:
        now = _utc_now(changed_at)
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO player_bindings(
                    qq_user_id, player_id, player_nick,
                    choice_completed, last_changed_at, created_at, updated_at
                )
                VALUES (?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(qq_user_id) DO UPDATE SET
                    player_id = excluded.player_id,
                    player_nick = excluded.player_nick,
                    choice_completed = 1,
                    last_changed_at = excluded.last_changed_at,
                    updated_at = excluded.updated_at
                WHERE player_bindings.player_id IS NOT excluded.player_id
                """,
                (qq_user_id, player_id, player_nick, now, now, now),
            )
        saved = self.get(qq_user_id)
        if saved.player_id != player_id:
            raise PlayerBindingWriteError(
                expected_player_id=player_id,
                actual_player_id=saved.player_id,
            )

    def decline(self, *, qq_user_id: int) -> None:
        now = _utc_now()
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO player_bindings(
                    qq_user_id, player_id, player_nick,
                    choice_completed, last_changed_at, created_at, updated_at
                )
                VALUES (?, NULL, '', 1, NULL, ?, ?)
                ON CONFLICT(qq_user_id) DO UPDATE SET
                    choice_completed = 1,
                    updated_at = excluded.updated_at
                """,
                (qq_user_id, now, now),
            )

    def unbind(
        self,
        *,
        qq_user_id: int,
        changed_at: datetime | None = None,
    ) -> bool:
        now = _utc_now(changed_at)
        with self._database.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE player_bindings
                SET player_id = NULL, player_nick = '',
                    choice_completed = 1, last_changed_at = ?, updated_at = ?
                WHERE qq_user_id = ? AND player_id IS NOT NULL
                """,
                (now, now, qq_user_id),
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
