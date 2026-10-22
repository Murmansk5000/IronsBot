from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.config.models.messaging import TeamAuditWelcomeConfig
from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.team_audit import SqliteTeamAuditReminderStore
from ironsbot.plugins.onebot.team_audit import plugin_contribution
from ironsbot.services.team import audit as audit_module
from ironsbot.services.team.audit import TeamAuditPendingReminder, TeamAuditService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import tzinfo
    from pathlib import Path


@pytest_asyncio.fixture(params=list(Platform))
async def audit(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[SimpleNamespace]:
    platform = request.param
    conversation = ConversationRef(platform, "group", "group", account_id="first")
    actor = ActorRef(platform, "member", "member", "group", account_id="first")
    now = datetime.now(timezone.utc) - timedelta(days=2)
    reminder = TeamAuditPendingReminder(
        conversation, actor, now, now + timedelta(hours=24)
    )
    store = SqliteTeamAuditReminderStore(
        tmp_path / "audit.sqlite", spawn=asyncio.create_task
    )
    await store.save(reminder)
    messenger = Mock(
        send=AsyncMock(return_value=SendResult(delivered=True, message_id="sent"))
    )
    probe = Mock(
        can_access=AsyncMock(return_value=True), has_member=AsyncMock(return_value=True)
    )
    config = TeamAuditWelcomeConfig(
        enabled=True, followup_enabled=True, final_followup_enabled=False
    )
    service = TeamAuditService(
        config, store, Mock(enabled_for=Mock(return_value=True)), messenger, probe
    )
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.start(paused=True)
    try:
        yield SimpleNamespace(
            service=service,
            store=store,
            scheduler=scheduler,
            messenger=messenger,
            probe=probe,
            reminder=reminder,
            config=config,
        )
    finally:
        scheduler.shutdown(wait=False)
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_audit_startup_owns_scan_and_connections_only_restore(
    audit: SimpleNamespace,
) -> None:
    lifecycle = ApplicationLifecycle.from_contributions(
        (plugin_contribution(scheduler=audit.scheduler, service=audit.service),),
        task_owner=TaskOwner(),
    )
    await lifecycle.startup()
    ids = {job.id for job in audit.scheduler.get_jobs()}
    assert "team_audit_followup_scan" in ids
    assert len(ids) == len(("scan", "pending"))
    await lifecycle.bot_connect(SimpleNamespace(self_id="11"))
    await lifecycle.bot_connect(SimpleNamespace(self_id="12"))
    assert {job.id for job in audit.scheduler.get_jobs()} == ids
    audit.messenger.send.assert_not_awaited()

    audit.scheduler.add_job(
        lambda: None,
        "date",
        id="foreign",
        run_date=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await lifecycle.shutdown()
    assert [job.id for job in audit.scheduler.get_jobs()] == ["foreign"]
    assert (await audit.store.list_all()) == [audit.reminder]


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled", ["all", "followup"])
async def test_disabled_audit_registers_no_empty_scan(
    audit: SimpleNamespace, disabled: str
) -> None:
    if disabled == "all":
        audit.config.enabled = False
    else:
        audit.config.followup_enabled = False
    await audit.service.start(scheduler=audit.scheduler)
    assert audit.scheduler.get_jobs() == []


@pytest.mark.asyncio
async def test_audit_jobs_separate_account_scopes(audit: SimpleNamespace) -> None:
    other = audit.reminder._replace(
        conversation=replace(audit.reminder.conversation, account_id="second"),
        actor=replace(audit.reminder.actor, account_id="second"),
    )
    await audit.store.save(other)
    await audit.service.start(scheduler=audit.scheduler)
    assert len(audit.scheduler.get_jobs()) == len(("scan", "first", "second"))
    assert len(await audit.store.list_all()) == len(("first", "second"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replacement_stage", ["none", "before", "during_probe", "during_probe_due"]
)
async def test_scheduled_followup_does_not_send_future_or_replaced_reminder(
    audit: SimpleNamespace, replacement_stage: str
) -> None:
    now = datetime.now(timezone.utc)
    old = audit.reminder._replace(
        joined_at=now - timedelta(days=2), remind_at=now - timedelta(days=1)
    )
    new = old._replace(joined_at=now, remind_at=now + timedelta(days=1))
    if replacement_stage == "during_probe_due":
        new = new._replace(remind_at=now - timedelta(seconds=1))
    await audit.store.save(new if replacement_stage == "none" else old)
    audit.service.schedule(audit.scheduler, old)
    job = audit.scheduler.get_jobs()[0]
    if replacement_stage == "before":
        await audit.store.save(new)
    elif replacement_stage.startswith("during_probe"):

        async def has_member(*_args: object, **_kwargs: object) -> bool:
            await audit.store.save(new)
            return True

        audit.probe.has_member.side_effect = has_member
    await job.func(*job.args, **job.kwargs)
    audit.messenger.send.assert_not_awaited()
    assert await audit.store.list_all() == [new]


@pytest.mark.asyncio
@pytest.mark.parametrize("future", [False, True])
async def test_audit_due_boundary_is_inclusive(
    audit: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, *, future: bool
) -> None:
    instant = datetime.now(timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return instant.astimezone(tz)

    monkeypatch.setattr(audit_module, "datetime", Clock)
    reminder = audit.reminder._replace(
        remind_at=instant + timedelta(microseconds=int(future))
    )
    await audit.store.save(reminder)
    audit.service.schedule(audit.scheduler, reminder)
    job = audit.scheduler.get_jobs()[0]
    await job.func(*job.args, **job.kwargs)
    if future:
        audit.messenger.send.assert_not_awaited()
        assert await audit.store.list_all() == [reminder]
    else:
        audit.messenger.send.assert_awaited_once()
        assert await audit.store.list_all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("restart", [False, True])
async def test_stop_during_membership_probe_preserves_pending(
    audit: SimpleNamespace, *, restart: bool
) -> None:
    async def has_member(*_args: object, **_kwargs: object) -> bool:
        audit.service.stop(scheduler=audit.scheduler)
        if restart:
            await audit.service.start(scheduler=audit.scheduler)
        return False

    audit.probe.has_member.side_effect = has_member
    await audit.service.send_followup(
        audit.reminder.conversation, audit.reminder.actor, scheduler=audit.scheduler
    )
    assert await audit.store.list_all() == [audit.reminder]
    audit.messenger.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_overlapping_followups_send_once_then_recheck_store(
    audit: SimpleNamespace,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def send(*_args: object) -> SendResult:
        entered.set()
        await release.wait()
        return SendResult(delivered=True, message_id="sent")

    audit.messenger.send.side_effect = send
    first = asyncio.create_task(
        audit.service.send_followup(
            audit.reminder.conversation, audit.reminder.actor, scheduler=audit.scheduler
        )
    )
    second: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        second = asyncio.create_task(
            audit.service.send_followup(
                audit.reminder.conversation,
                audit.reminder.actor,
                scheduler=audit.scheduler,
            )
        )
        await asyncio.sleep(0)
        audit.messenger.send.assert_awaited_once()
        release.set()
        await asyncio.gather(first, second)
        await audit.service.send_followup(
            audit.reminder.conversation, audit.reminder.actor, scheduler=audit.scheduler
        )
        audit.messenger.send.assert_awaited_once()
        assert (await audit.store.list_all()) == []
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["failure", "cancelled", "exception"])
async def test_followup_releases_inflight_without_discarding_pending(
    audit: SimpleNamespace, outcome: str
) -> None:
    if outcome == "failure":
        audit.messenger.send.return_value = SendResult(
            delivered=False, error_code="rejected"
        )
        await audit.service.send_followup(
            audit.reminder.conversation, audit.reminder.actor, scheduler=audit.scheduler
        )
    else:
        error = (
            asyncio.CancelledError()
            if outcome == "cancelled"
            else RuntimeError("failed")
        )
        audit.messenger.send.side_effect = error
        with pytest.raises(type(error)):
            await audit.service.send_followup(
                audit.reminder.conversation,
                audit.reminder.actor,
                scheduler=audit.scheduler,
            )
    assert (await audit.store.list_all()) == [audit.reminder]
    audit.messenger.send.side_effect = None
    audit.messenger.send.return_value = SendResult(delivered=True, message_id="retry")
    await audit.service.send_followup(
        audit.reminder.conversation, audit.reminder.actor, scheduler=audit.scheduler
    )
    assert (await audit.store.list_all()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["welcome", "followup"])
async def test_audit_failures_log_only_safe_disposition(
    audit: SimpleNamespace, caplog: pytest.LogCaptureFixture, stage: str
) -> None:
    audit.messenger.send.return_value = SendResult(
        delivered=False,
        error_code="sensitive-code",
        error_message="sensitive-body",
        failure_kind=DeliveryFailureKind.UNCERTAIN,
    )
    if stage == "welcome":
        await audit.service.welcome(
            conversation=audit.reminder.conversation,
            actor=audit.reminder.actor,
            joined_at=audit.reminder.joined_at,
            scheduler=audit.scheduler,
        )
    else:
        await audit.service.send_followup(
            audit.reminder.conversation, audit.reminder.actor, scheduler=audit.scheduler
        )
    assert "failure_kind=uncertain" in caplog.text
    assert "sensitive-code" not in caplog.text
    assert "sensitive-body" not in caplog.text
