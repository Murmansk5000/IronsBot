# SPDX-License-Identifier: MIT
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ironsbot.config import get_app_config

from .planning import reminder_key

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import ActivityReminder

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _cache_path(cache_path: Path | None = None) -> Path:
    path = cache_path or get_app_config().activity.cache_path
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect_cache(cache_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(_cache_path(cache_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_activity_reminders (
            activity_id INTEGER NOT NULL,
            end_time TEXT NOT NULL,
            lead_hours INTEGER NOT NULL,
            sent_at TEXT NOT NULL,
            PRIMARY KEY (activity_id, end_time, lead_hours)
        )
        """
    )
    conn.commit()
    return conn


def filter_unsent(
    reminders: Iterable[ActivityReminder],
    *,
    cache_path: Path | None = None,
) -> list[ActivityReminder]:
    with _connect_cache(cache_path) as conn:
        unsent: list[ActivityReminder] = []
        for reminder in reminders:
            activity_id, end_time, lead_hours = reminder_key(reminder)
            sent = conn.execute(
                """
                SELECT 1 FROM sent_activity_reminders
                WHERE activity_id = ? AND end_time = ? AND lead_hours = ?
                """,
                (activity_id, end_time, lead_hours),
            ).fetchone()
            if sent is None:
                unsent.append(reminder)
        return unsent


def mark_sent(
    reminders: Iterable[ActivityReminder],
    *,
    cache_path: Path | None = None,
    sent_at: datetime | None = None,
) -> None:
    sent_at_text = (sent_at or datetime.now(LOCAL_TZ)).isoformat()
    with _connect_cache(cache_path) as conn:
        conn.executemany(
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
        conn.commit()
