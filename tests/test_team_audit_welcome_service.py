import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ironsbot.integrations.storage.team_audit import SqliteTeamAuditReminderStore
from ironsbot.services.team.audit import TeamAuditPendingReminder

GROUP_ID = 123
USER_ID = 456
FIRST_FOLLOWUP_STEP = 1
FINAL_FOLLOWUP_STEP = 2


def _reminder(
    joined_at: datetime,
    *,
    delay_hours: float = 24,
    step: int = FIRST_FOLLOWUP_STEP,
) -> TeamAuditPendingReminder:
    return TeamAuditPendingReminder(
        GROUP_ID,
        USER_ID,
        joined_at,
        joined_at + timedelta(hours=delay_hours),
        step,
    )


def test_team_audit_pending_reminder_roundtrip(tmp_path: Path) -> None:
    store = SqliteTeamAuditReminderStore(tmp_path / "team_audit" / "pending.sqlite")
    joined_at = datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc)
    reminder = _reminder(joined_at)

    store.save(reminder)

    assert store.get(GROUP_ID, USER_ID) == reminder
    assert store.list_all() == [reminder]


def test_team_audit_pending_reminder_upsert_and_clear(tmp_path: Path) -> None:
    store = SqliteTeamAuditReminderStore(tmp_path / "pending.sqlite")
    first = _reminder(datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc))
    updated = _reminder(
        datetime(2026, 6, 26, 2, 0, tzinfo=timezone.utc),
        delay_hours=48,
        step=FINAL_FOLLOWUP_STEP,
    )

    store.save(first)
    store.save(updated)

    assert store.list_all() == [updated]
    store.clear(GROUP_ID, USER_ID)
    assert store.list_all() == []


def test_team_audit_pending_reminder_uses_platform_identity_schema(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "pending.sqlite"
    store = SqliteTeamAuditReminderStore(cache_path)
    store.save(_reminder(datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc)))

    with sqlite3.connect(cache_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(pending_team_audit_reminders)")
        }

    assert {"conversation_platform", "actor_platform"} <= columns
    assert "group_id" not in columns
    assert "user_id" not in columns
