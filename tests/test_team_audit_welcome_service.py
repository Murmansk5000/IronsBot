from datetime import datetime, timezone
from pathlib import Path

from ironsbot.services.team_audit_welcome import (
    clear_team_audit_pending_reminder,
    list_team_audit_pending_reminders,
    record_team_audit_pending_reminder,
)

GROUP_ID = 123
USER_ID = 456
FOLLOWUP_DELAY_HOURS = 24


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
        delay_hours=FOLLOWUP_DELAY_HOURS,
    )

    assert list_team_audit_pending_reminders(cache_path) == [updated]

    clear_team_audit_pending_reminder(
        cache_path,
        group_id=GROUP_ID,
        user_id=USER_ID,
    )

    assert list_team_audit_pending_reminders(cache_path) == []
