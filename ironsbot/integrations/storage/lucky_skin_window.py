# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path

_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS lucky_skin_window_cache (
    player_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    skin_ids_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (player_id, day)
)
"""
_SCHEMA = """
CREATE TABLE IF NOT EXISTS lucky_skin_window_cache (
    player_id INTEGER PRIMARY KEY,
    skin_ids_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
)
"""
_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS lucky_skin_window_cache_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cache_day TEXT NOT NULL
)
"""
_MIGRATIONS = (
    SqliteMigration(1, (_LEGACY_SCHEMA,)),
    SqliteMigration(2, (_LEGACY_SCHEMA,)),
    SqliteMigration(
        3,
        (
            "DROP TABLE IF EXISTS lucky_skin_window_cache",
            _SCHEMA,
            _STATE_SCHEMA,
        ),
    ),
)
_OFFER_COUNT = 4


class SqliteLuckySkinWindowCache:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace="skin_window",
        )

    def initialize(self) -> None:
        """Create or migrate the persistent store without reading a player row."""
        with self._database.connect():
            pass

    def get(self, *, player_id: int) -> tuple[int, ...] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT skin_ids_json FROM lucky_skin_window_cache "
                "WHERE player_id = ?",
                (player_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            values = json.loads(str(row[0]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(values, list) or len(values) != _OFFER_COUNT:
            return None
        try:
            skin_ids = tuple(int(value) for value in values)
        except (TypeError, ValueError):
            return None
        return skin_ids if all(skin_id > 0 for skin_id in skin_ids) else None

    def prepare_day(self, *, day: str) -> None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT cache_day FROM lucky_skin_window_cache_state WHERE id = 1"
            ).fetchone()
            if row is not None and row[0] == day:
                return
            connection.execute(
                "DELETE FROM lucky_skin_window_cache",
            )
            connection.execute(
                """
                INSERT INTO lucky_skin_window_cache_state (id, cache_day)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET cache_day = excluded.cache_day
                """,
                (day,),
            )

    def put_if_absent(
        self,
        *,
        player_id: int,
        skin_ids: tuple[int, ...],
    ) -> tuple[int, ...]:
        payload = json.dumps(list(skin_ids), separators=(",", ":"))
        with self._database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO lucky_skin_window_cache "
                "(player_id, skin_ids_json, recorded_at) VALUES (?, ?, ?)",
                (
                    player_id,
                    payload,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return self.get(player_id=player_id) or skin_ids
