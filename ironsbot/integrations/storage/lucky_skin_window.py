# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    open_sqlite_connection,
    resolve_sqlite_path,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

logger = logging.getLogger(__name__)

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
    def __init__(
        self,
        path: str | Path,
        *,
        legacy_paths: Iterable[str | Path] = (),
    ) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace="skin_window",
        )
        self._legacy_paths = tuple(resolve_sqlite_path(item) for item in legacy_paths)

    def initialize(self) -> None:
        """Create or migrate the persistent store without reading a player row."""
        with self._database.connect():
            pass

    def get(self, *, player_id: int, day: str) -> tuple[int, ...] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT skin_ids_json FROM lucky_skin_window_cache "
                "WHERE player_id = ?",
                (player_id,),
            ).fetchone()
        if row is not None and (skin_ids := _parse_skin_ids(row[0])) is not None:
            return skin_ids
        return self._restore_legacy_result(player_id=player_id, day=day)

    def _restore_legacy_result(
        self,
        *,
        player_id: int,
        day: str,
    ) -> tuple[int, ...] | None:
        for path in self._legacy_paths:
            if not path.is_file():
                continue
            skin_ids = _read_legacy_result(path, player_id=player_id, day=day)
            if skin_ids is None:
                continue
            persisted = self.put_if_absent(
                player_id=player_id,
                skin_ids=skin_ids,
            )
            logger.info(
                "lucky skin window legacy cache imported: player_id=%s day=%s path=%s",
                player_id,
                day,
                path,
            )
            return persisted
        return None

    def _get_current(self, *, player_id: int) -> tuple[int, ...] | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT skin_ids_json FROM lucky_skin_window_cache "
                "WHERE player_id = ?",
                (player_id,),
            ).fetchone()
        return None if row is None else _parse_skin_ids(row[0])

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
        return self._get_current(player_id=player_id) or skin_ids


def _read_legacy_result(
    path: Path,
    *,
    player_id: int,
    day: str,
) -> tuple[int, ...] | None:
    try:
        with open_sqlite_connection(path, read_only=True) as connection:
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(lucky_skin_window_cache)"
                )
            }
            if {"player_id", "day", "skin_ids_json"} <= columns:
                row = connection.execute(
                    "SELECT skin_ids_json FROM lucky_skin_window_cache "
                    "WHERE player_id = ? AND day = ?",
                    (player_id, day),
                ).fetchone()
            elif {"player_id", "skin_ids_json"} <= columns and _legacy_day_matches(
                connection,
                day,
            ):
                row = connection.execute(
                    "SELECT skin_ids_json FROM lucky_skin_window_cache "
                    "WHERE player_id = ?",
                    (player_id,),
                ).fetchone()
            else:
                return None
    except sqlite3.Error:
        logger.warning("lucky skin window legacy cache unreadable: path=%s", path)
        return None
    return None if row is None else _parse_skin_ids(row[0])


def _legacy_day_matches(connection: sqlite3.Connection, day: str) -> bool:
    try:
        row = connection.execute(
            "SELECT cache_day FROM lucky_skin_window_cache_state WHERE id = 1"
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None and str(row[0]) == day


def _parse_skin_ids(payload: object) -> tuple[int, ...] | None:
    try:
        values = json.loads(str(payload))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(values, list) or len(values) != _OFFER_COUNT:
        return None
    try:
        skin_ids = tuple(int(value) for value in values)
    except (TypeError, ValueError):
        return None
    return skin_ids if all(skin_id > 0 for skin_id in skin_ids) else None
