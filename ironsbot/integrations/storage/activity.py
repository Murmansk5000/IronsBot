# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime
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
SENT_ACTIVITY_REMINDERS_MIGRATIONS = (
    SqliteMigration(1, (SENT_ACTIVITY_REMINDERS_SCHEMA,)),
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
