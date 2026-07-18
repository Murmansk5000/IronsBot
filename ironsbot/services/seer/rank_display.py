# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractContextManager

    from ironsbot.config.models.seer import RankQueryConfig


@dataclass(frozen=True, slots=True)
class RankDisplayLimitCommand:
    limit: int


RANK_DISPLAY_LIMIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS group_rank_display_limits (
    group_id INTEGER PRIMARY KEY,
    display_limit INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by INTEGER NOT NULL
)
"""
RANK_DISPLAY_LIMIT_MIGRATIONS = (
    SqliteMigration(1, (RANK_DISPLAY_LIMIT_SCHEMA,)),
)


@dataclass(frozen=True, slots=True)
class RankDisplayService:
    config: RankQueryConfig
    group_aliases: Mapping[str, int]

    def limit_for_group(self, group_id: int | None) -> int:
        return self._clamp(
            self._stored_group_limit(group_id)
            or self._configured_group_limit(group_id)
            or self.config.display_limit
        )

    def set_group_limit(self, group_id: int, user_id: int, limit: int) -> None:
        with self._connect() as conn:
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
                    self._clamp(limit),
                    datetime.now(timezone.utc).isoformat(),
                    user_id,
                ),
            )

    def _configured_group_limit(self, group_id: int | None) -> int | None:
        if group_id is None:
            return None
        direct = self.config.display_limits.get(str(group_id))
        if direct is not None:
            return direct
        return next(
            (
                self.config.display_limits[alias]
                for alias, alias_group_id in self.group_aliases.items()
                if alias_group_id == group_id
                and alias in self.config.display_limits
            ),
            None,
        )

    def _stored_group_limit(self, group_id: int | None) -> int | None:
        if group_id is None:
            return None
        try:
            with self._connect() as conn:
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

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return SqliteDatabase(
            self.config.display_limit_path,
            migrations=RANK_DISPLAY_LIMIT_MIGRATIONS,
        ).connect()

    def _clamp(self, value: int) -> int:
        return max(1, min(int(value), self.config.max_display_limit))


def parse_rank_display_limit_command(text: str) -> RankDisplayLimitCommand | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    command = "".join(stripped[1:].split()).lower()
    prefixes = (
        "榜单显示条数",
        "榜单显示数量",
        "榜单默认条数",
        "榜单默认数量",
        "榜单显示",
        "榜单条数",
    )
    prefix = next((item for item in prefixes if command.startswith(item)), None)
    if prefix is None:
        return None

    value = command[len(prefix) :]
    match = re.fullmatch(r"(\d+)(?:名|条)?", value)
    if match is None:
        return None
    return RankDisplayLimitCommand(limit=int(match.group(1)))
