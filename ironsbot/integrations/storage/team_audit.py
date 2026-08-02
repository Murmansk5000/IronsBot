# SPDX-License-Identifier: MIT
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    ensure_sqlite_columns,
)
from ironsbot.services.team.audit import TeamAuditPendingReminder

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_team_audit_reminders (
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    joined_at TEXT NOT NULL,
    remind_at TEXT NOT NULL,
    step INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (group_id, user_id)
)
"""


def _ensure_step_column(connection: sqlite3.Connection) -> None:
    ensure_sqlite_columns(
        connection,
        table_name="pending_team_audit_reminders",
        columns={"step": "step INTEGER NOT NULL DEFAULT 1"},
    )


_MIGRATIONS = (SqliteMigration(1, (_SCHEMA,), _ensure_step_column),)
MIGRATION_NAMESPACE = "team_audit"


class SqliteTeamAuditReminderStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
            row_factory=sqlite3.Row,
        )

    def save(self, reminder: TeamAuditPendingReminder) -> None:
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_team_audit_reminders (
                    group_id, user_id, joined_at, remind_at, step
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(group_id, user_id) DO UPDATE SET
                    joined_at = excluded.joined_at,
                    remind_at = excluded.remind_at,
                    step = excluded.step
                """,
                (
                    reminder.group_id,
                    reminder.user_id,
                    _datetime_text(reminder.joined_at),
                    _datetime_text(reminder.remind_at),
                    reminder.step,
                ),
            )

    def get(
        self,
        group_id: int,
        user_id: int,
    ) -> TeamAuditPendingReminder | None:
        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT group_id, user_id, joined_at, remind_at, step
                FROM pending_team_audit_reminders
                WHERE group_id = ? AND user_id = ?
                """,
                (group_id, user_id),
            ).fetchone()
        return None if row is None else _row_to_reminder(row)

    def list_all(self) -> list[TeamAuditPendingReminder]:
        with self._database.connect() as conn:
            rows = conn.execute(
                """
                SELECT group_id, user_id, joined_at, remind_at, step
                FROM pending_team_audit_reminders
                ORDER BY remind_at, group_id, user_id
                """
            ).fetchall()
        return [_row_to_reminder(row) for row in rows]

    def clear(self, group_id: int, user_id: int) -> None:
        with self._database.connect() as conn:
            conn.execute(
                "DELETE FROM pending_team_audit_reminders "
                "WHERE group_id = ? AND user_id = ?",
                (group_id, user_id),
            )


def _row_to_reminder(row: sqlite3.Row) -> TeamAuditPendingReminder:
    return TeamAuditPendingReminder(
        int(row["group_id"]),
        int(row["user_id"]),
        _parse_datetime(row["joined_at"]),
        _parse_datetime(row["remind_at"]),
        max(1, int(row["step"])),
    )


def _datetime_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
