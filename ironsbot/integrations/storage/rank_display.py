# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS group_rank_display_limits (
    group_id INTEGER PRIMARY KEY,
    display_limit INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by INTEGER NOT NULL
)
"""
_MIGRATIONS = (SqliteMigration(1, (_SCHEMA,)),)


class SqliteRankDisplayStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(path, migrations=_MIGRATIONS)

    def get(self, group_id: int) -> int | None:
        try:
            with self._database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT display_limit
                    FROM group_rank_display_limits
                    WHERE group_id = ?
                    """,
                    (group_id,),
                ).fetchone()
        except sqlite3.Error:
            return None
        return int(row[0]) if row is not None else None

    def set(self, group_id: int, user_id: int, limit: int) -> None:
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO group_rank_display_limits (
                    group_id, display_limit, updated_at, updated_by
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET
                    display_limit = excluded.display_limit,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (
                    group_id,
                    limit,
                    datetime.now(timezone.utc).isoformat(),
                    user_id,
                ),
            )
