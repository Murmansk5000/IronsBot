# SPDX-License-Identifier: MIT
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ironsbot.shared.sqlite import ensure_sqlite_column, open_sqlite

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class TeamAuditPendingReminder:
    group_id: int
    user_id: int
    joined_at: datetime
    remind_at: datetime
    step: int = 1


def record_team_audit_pending_reminder(  # noqa: PLR0913
    cache_path: str | Path,
    *,
    group_id: int,
    user_id: int,
    joined_at: datetime,
    delay_hours: float,
    step: int = 1,
) -> TeamAuditPendingReminder:
    joined_at = _as_utc(joined_at)
    reminder = TeamAuditPendingReminder(
        group_id=group_id,
        user_id=user_id,
        joined_at=joined_at,
        remind_at=joined_at + timedelta(hours=delay_hours),
        step=max(1, int(step)),
    )
    with _connect(cache_path) as conn:
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
    return reminder


def get_team_audit_pending_reminder(
    cache_path: str | Path,
    *,
    group_id: int,
    user_id: int,
) -> TeamAuditPendingReminder | None:
    with _connect(cache_path) as conn:
        row = conn.execute(
            """
            SELECT group_id, user_id, joined_at, remind_at, step
            FROM pending_team_audit_reminders
            WHERE group_id = ? AND user_id = ?
            """,
            (group_id, user_id),
        ).fetchone()

    return None if row is None else _row_to_reminder(row)


def list_team_audit_pending_reminders(
    cache_path: str | Path,
) -> list[TeamAuditPendingReminder]:
    with _connect(cache_path) as conn:
        rows = conn.execute(
            """
            SELECT group_id, user_id, joined_at, remind_at, step
            FROM pending_team_audit_reminders
            ORDER BY remind_at, group_id, user_id
            """
        ).fetchall()

    return [_row_to_reminder(row) for row in rows]


def clear_team_audit_pending_reminder(
    cache_path: str | Path,
    *,
    group_id: int,
    user_id: int,
) -> None:
    with _connect(cache_path) as conn:
        conn.execute(
            """
            DELETE FROM pending_team_audit_reminders
            WHERE group_id = ? AND user_id = ?
            """,
            (group_id, user_id),
        )


@contextmanager
def _connect(cache_path: str | Path) -> Iterator[sqlite3.Connection]:
    with open_sqlite(cache_path, row_factory=sqlite3.Row) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_team_audit_reminders (
                group_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                step INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (group_id, user_id)
            )
            """
        )
        _ensure_step_column(conn)
        yield conn


def _ensure_step_column(conn: sqlite3.Connection) -> None:
    ensure_sqlite_column(
        conn,
        table_name="pending_team_audit_reminders",
        column_name="step",
        column_definition="step INTEGER NOT NULL DEFAULT 1",
    )


def _row_to_reminder(row: sqlite3.Row) -> TeamAuditPendingReminder:
    return TeamAuditPendingReminder(
        group_id=int(row["group_id"]),
        user_id=int(row["user_id"]),
        joined_at=_parse_datetime(row["joined_at"]),
        remind_at=_parse_datetime(row["remind_at"]),
        step=max(1, int(row["step"])),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _datetime_text(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _parse_datetime(value: str) -> datetime:
    return _as_utc(datetime.fromisoformat(value))


__all__ = [
    "TeamAuditPendingReminder",
    "clear_team_audit_pending_reminder",
    "get_team_audit_pending_reminder",
    "list_team_audit_pending_reminders",
    "record_team_audit_pending_reminder",
]
