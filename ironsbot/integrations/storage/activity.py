# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
)
from ironsbot.services.activity.planning import reminder_key

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.activity.models import ActivityReminder

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SENT_ACTIVITY_REMINDERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_activity_reminders (
    activity_id INTEGER NOT NULL,
    end_time TEXT NOT NULL,
    lead_hours INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (activity_id, end_time, lead_hours)
)
"""
ACTIVITY_WEEKLY_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS activity_weekly_snapshots (
    week_start TEXT NOT NULL,
    activity_id INTEGER NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (week_start, activity_id)
)
"""
SENT_ACTIVITY_REMINDERS_MIGRATIONS = (
    SqliteMigration(1, (SENT_ACTIVITY_REMINDERS_SCHEMA,)),
    SqliteMigration(2, (ACTIVITY_WEEKLY_SNAPSHOTS_SCHEMA,)),
)
MIGRATION_NAMESPACE = "activity_reminder"


class ActivitySentStore:
    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=SENT_ACTIVITY_REMINDERS_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def filter_unsent(
        self,
        reminders: list[ActivityReminder],
    ) -> list[ActivityReminder]:
        with self._database.connect() as connection:
            return [
                reminder
                for reminder in reminders
                if connection.execute(
                    """
                    SELECT 1 FROM sent_activity_reminders
                    WHERE activity_id = ? AND end_time = ? AND lead_hours = ?
                    """,
                    reminder_key(reminder),
                ).fetchone()
                is None
            ]

    def mark_sent(
        self,
        reminders: list[ActivityReminder],
        sent_at: datetime | None = None,
    ) -> None:
        sent_at_text = (sent_at or datetime.now(LOCAL_TZ)).isoformat()
        with self._database.connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO sent_activity_reminders
                (activity_id, end_time, lead_hours, sent_at)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (*reminder_key(reminder), sent_at_text)
                    for reminder in reminders
                ],
            )


class ActivitySnapshotStore:
    """Persist weekly activity membership for the user-facing change view."""

    def __init__(self, path: str | Path) -> None:
        self._database = SqliteDatabase(
            path,
            migrations=SENT_ACTIVITY_REMINDERS_MIGRATIONS,
            migration_namespace=MIGRATION_NAMESPACE,
        )

    def newly_observed_ids(
        self,
        activity_ids: set[int],
        observed_at: datetime,
    ) -> tuple[frozenset[int], bool]:
        current_week = _week_start(observed_at)
        previous_week = _week_start(observed_at - timedelta(days=7))
        observed_at_text = observed_at.astimezone(LOCAL_TZ).isoformat()

        with self._database.connect() as connection:
            previous_ids = {
                int(row[0])
                for row in connection.execute(
                    """
                    SELECT activity_id
                    FROM activity_weekly_snapshots
                    WHERE week_start = ?
                    """,
                    (previous_week,),
                )
            }
            if activity_ids:
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO activity_weekly_snapshots
                    (week_start, activity_id, observed_at)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (current_week, activity_id, observed_at_text)
                        for activity_id in sorted(activity_ids)
                    ],
                )

        return frozenset(activity_ids - previous_ids), bool(previous_ids)


def _week_start(value: datetime) -> str:
    local_value = value.astimezone(LOCAL_TZ)
    return (local_value - timedelta(days=local_value.weekday())).date().isoformat()
