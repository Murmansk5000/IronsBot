import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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


@pytest.mark.asyncio
async def test_team_audit_pending_reminder_roundtrip(tmp_path: Path) -> None:
    store = SqliteTeamAuditReminderStore(
        tmp_path / "team_audit" / "pending.sqlite", spawn=asyncio.create_task
    )
    joined_at = datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc)
    reminder = _reminder(joined_at)

    await store.save(reminder)

    assert (await store.get(_conversation(), _actor())) == reminder
    assert (await store.list_all()) == [reminder]


@pytest.mark.asyncio
async def test_team_audit_pending_reminder_upsert_and_clear(tmp_path: Path) -> None:
    store = SqliteTeamAuditReminderStore(
        tmp_path / "pending.sqlite", spawn=asyncio.create_task
    )
    first = _reminder(datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc))
    updated = _reminder(
        datetime(2026, 6, 26, 2, 0, tzinfo=timezone.utc),
        delay_hours=48,
        step=FINAL_FOLLOWUP_STEP,
    )

    await store.save(first)
    await store.save(updated)

    assert (await store.list_all()) == [updated]
    assert await store.transition(updated)
    assert (await store.list_all()) == []


@pytest.mark.asyncio
async def test_team_audit_pending_reminder_uses_platform_identity_schema(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "pending.sqlite"
    store = SqliteTeamAuditReminderStore(cache_path, spawn=asyncio.create_task)
    await store.save(_reminder(datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc)))

    with sqlite3.connect(cache_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(pending_team_audit_reminders)")
        }

    assert {"conversation_platform", "actor_platform"} <= columns
    assert "group_id" not in columns
    assert "user_id" not in columns


@pytest.mark.asyncio
async def test_team_audit_pending_reminder_preserves_non_onebot_identity(
    tmp_path: Path,
) -> None:
    store = SqliteTeamAuditReminderStore(
        tmp_path / "pending.sqlite", spawn=asyncio.create_task
    )
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

    await store.save(reminder)

    assert (await store.get(conversation, actor)) == reminder
    assert (await store.list_all()) == [reminder]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["joined_at", "remind_at", "step"])
@pytest.mark.parametrize("advance", [False, True])
async def test_reminder_transition_checks_complete_expected_state(
    tmp_path: Path, changed: str, *, advance: bool
) -> None:
    store = SqliteTeamAuditReminderStore(
        tmp_path / "pending.sqlite", spawn=asyncio.create_task
    )
    old = _reminder(datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc))
    if changed == "joined_at":
        current = old._replace(joined_at=old.joined_at + timedelta(seconds=1))
    elif changed == "remind_at":
        current = old._replace(remind_at=old.remind_at + timedelta(seconds=1))
    else:
        current = old._replace(step=FINAL_FOLLOWUP_STEP)
    await store.save(current)
    replacement = old._replace(step=FINAL_FOLLOWUP_STEP) if advance else None
    assert not await store.transition(old, replacement=replacement)
    assert await store.get(current.conversation, current.actor) == current


@pytest.mark.asyncio
async def test_concurrent_reminder_transitions_have_one_winner(tmp_path: Path) -> None:
    store = SqliteTeamAuditReminderStore(
        tmp_path / "pending.sqlite", spawn=asyncio.create_task
    )
    old = _reminder(datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc))
    next_step = old._replace(step=FINAL_FOLLOWUP_STEP)
    await store.save(old)
    outcomes = await asyncio.gather(
        store.transition(old), store.transition(old, replacement=next_step)
    )
    assert sum(outcomes) == 1
    assert await store.get(old.conversation, old.actor) == (
        None if outcomes[0] else next_step
    )


@pytest.mark.asyncio
async def test_reminder_transition_preserves_other_account_and_identity(
    tmp_path: Path,
) -> None:
    store = SqliteTeamAuditReminderStore(
        tmp_path / "pending.sqlite", spawn=asyncio.create_task
    )
    first = _reminder(datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc))
    other = first._replace(
        conversation=ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID), "other")
    )
    await store.save(first)
    await store.save(other)
    with pytest.raises(ValueError, match="cannot change its identity"):
        await store.transition(first, replacement=other)
    assert set(await store.list_all()) == {first, other}
    assert await store.transition(first)
    assert not await store.transition(first)
    assert await store.list_all() == [other]


def _conversation() -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID))


def _actor() -> ActorRef:
    return ActorRef(
        Platform.ONEBOT,
        str(USER_ID),
        kind="member",
        scope_id=str(GROUP_ID),
    )
