# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lucky_skin_watch_preferences (
    qq_user_id INTEGER PRIMARY KEY,
    skin_ids_json TEXT NOT NULL,
    initialized_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""
_MIGRATIONS = (SqliteMigration(1, (_SCHEMA,)),)
MIGRATION_NAMESPACE = "lucky_skin_watch"


class SqliteLuckySkinWatchPreferenceStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def get(self, qq_user_id: int) -> tuple[int, ...] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT skin_ids_json FROM lucky_skin_watch_preferences "
                "WHERE qq_user_id = ?",
                (qq_user_id,),
            ).fetchone()
        if row is None:
            return None
        return _decode_skin_ids(row[0])

    def set(self, qq_user_id: int, skin_ids: tuple[int, ...]) -> None:
        normalized = _normalize_skin_ids(skin_ids)
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(normalized, separators=(",", ":"))
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO lucky_skin_watch_preferences(
                    qq_user_id, skin_ids_json, initialized_at, updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(qq_user_id) DO UPDATE SET
                    skin_ids_json = excluded.skin_ids_json,
                    updated_at = excluded.updated_at
                """,
                (qq_user_id, payload, now, now),
            )


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
