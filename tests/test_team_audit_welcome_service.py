import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
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
        _conversation(),
        _actor(),
        joined_at,
        joined_at + timedelta(hours=delay_hours),
        step,
    )


def test_team_audit_pending_reminder_roundtrip(tmp_path: Path) -> None:
    store = SqliteTeamAuditReminderStore(tmp_path / "team_audit" / "pending.sqlite")
    joined_at = datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc)
    reminder = _reminder(joined_at)

    store.save(reminder)

    assert store.get(_conversation(), _actor()) == reminder
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
    store.clear(_conversation(), _actor())
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


def test_team_audit_pending_reminder_preserves_non_onebot_identity(
    tmp_path: Path,
) -> None:
    store = SqliteTeamAuditReminderStore(tmp_path / "pending.sqlite")
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "guild", "guild-1")
    actor = ActorRef(
        Platform.QQ_OFFICIAL, "member-1", kind="member", scope_id="guild-1"
    )
    reminder = TeamAuditPendingReminder(
        conversation,
        actor,
        datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 27, 1, 0, tzinfo=timezone.utc),
    )

    store.save(reminder)

    assert store.get(conversation, actor) == reminder
    assert store.list_all() == [reminder]


def _conversation() -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID))


def _actor() -> ActorRef:
    return ActorRef(
        Platform.ONEBOT,
        str(USER_ID),
        kind="member",
        scope_id=str(GROUP_ID),
    )
