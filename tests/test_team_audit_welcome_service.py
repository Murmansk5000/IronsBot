import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ironsbot.services.team_audit_welcome import (
    clear_team_audit_pending_reminder,
    get_team_audit_pending_reminder,
    list_team_audit_pending_reminders,
    record_team_audit_pending_reminder,
)

GROUP_ID = 123
USER_ID = 456
FOLLOWUP_DELAY_HOURS = 24
FINAL_FOLLOWUP_DELAY_HOURS = 48
FIRST_FOLLOWUP_STEP = 1
FINAL_FOLLOWUP_STEP = 2


def test_team_audit_pending_reminder_roundtrip(tmp_path: Path) -> None:
    cache_path = tmp_path / "team_audit" / "pending.sqlite"
    joined_at = datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc)

    reminder = record_team_audit_pending_reminder(
        cache_path,
        group_id=GROUP_ID,
        user_id=USER_ID,
        joined_at=joined_at,
        delay_hours=FOLLOWUP_DELAY_HOURS,
    )

    assert reminder.group_id == GROUP_ID
    assert reminder.user_id == USER_ID
    assert reminder.joined_at == joined_at
    assert reminder.remind_at.isoformat() == "2026-06-27T01:00:00+00:00"
    assert reminder.step == FIRST_FOLLOWUP_STEP
    assert (
        get_team_audit_pending_reminder(
            cache_path,
            group_id=GROUP_ID,
            user_id=USER_ID,
        )
        == reminder
    )
    assert list_team_audit_pending_reminders(cache_path) == [reminder]


def test_team_audit_pending_reminder_upsert_and_clear(tmp_path: Path) -> None:
    cache_path = tmp_path / "pending.sqlite"
    first_joined_at = datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc)
    second_joined_at = datetime(2026, 6, 26, 2, 0, tzinfo=timezone.utc)

    record_team_audit_pending_reminder(
        cache_path,
        group_id=GROUP_ID,
        user_id=USER_ID,
        joined_at=first_joined_at,
        delay_hours=FOLLOWUP_DELAY_HOURS,
    )
    updated = record_team_audit_pending_reminder(
        cache_path,
        group_id=GROUP_ID,
        user_id=USER_ID,
        joined_at=second_joined_at,
        delay_hours=FINAL_FOLLOWUP_DELAY_HOURS,
        step=FINAL_FOLLOWUP_STEP,
    )

    assert updated.step == FINAL_FOLLOWUP_STEP
    assert updated.remind_at.isoformat() == "2026-06-28T02:00:00+00:00"
    assert list_team_audit_pending_reminders(cache_path) == [updated]

    clear_team_audit_pending_reminder(
        cache_path,
        group_id=GROUP_ID,
        user_id=USER_ID,
    )

    assert list_team_audit_pending_reminders(cache_path) == []


def test_team_audit_pending_reminder_migrates_old_schema(tmp_path: Path) -> None:
    cache_path = tmp_path / "old_pending.sqlite"
    joined_at = "2026-06-26T01:00:00+00:00"
    remind_at = "2026-06-27T01:00:00+00:00"

    with sqlite3.connect(cache_path) as conn:
        conn.execute(
            """
            CREATE TABLE pending_team_audit_reminders (
                group_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                PRIMARY KEY (group_id, user_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO pending_team_audit_reminders (
                group_id, user_id, joined_at, remind_at
            ) VALUES (?, ?, ?, ?)
            """,
            (GROUP_ID, USER_ID, joined_at, remind_at),
        )

    reminders = list_team_audit_pending_reminders(cache_path)

    assert len(reminders) == 1
    assert reminders[0].step == FIRST_FOLLOWUP_STEP
