from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.messaging import TeamAuditWelcomeConfig
from ironsbot.core.outbound import SendResult
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage import sqlite as sqlite_storage
from ironsbot.integrations.storage.team_audit import SqliteTeamAuditReminderStore
from ironsbot.services.team.audit import TeamAuditPendingReminder, TeamAuditService

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path
    from typing import Any


@pytest.mark.asyncio
async def test_pending_restore_opens_database_outside_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_thread = threading.get_ident()
    threads: list[int] = []
    original = sqlite_storage.open_sqlite_connection

    def connect(path: str | Path) -> sqlite3.Connection:
        threads.append(threading.get_ident())
        return original(path)

    monkeypatch.setattr(sqlite_storage, "open_sqlite_connection", connect)
    service = TeamAuditService(
        TeamAuditWelcomeConfig(enabled=True, followup_enabled=True),
        SqliteTeamAuditReminderStore(
            tmp_path / "audit.sqlite", spawn=asyncio.create_task
        ),
        Mock(),
        Mock(),
        Mock(),
    )
    await service.schedule_pending(Mock())
    assert threads
    assert all(thread != event_thread for thread in threads)


@pytest.mark.asyncio
async def test_cancelled_database_read_holds_followup_guard_until_worker_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = ConversationRef(Platform.ONEBOT, "group", "456")
    actor = ActorRef(Platform.ONEBOT, "101", "member", "456")
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
    service = TeamAuditService(
        TeamAuditWelcomeConfig(
            enabled=True, followup_enabled=True, final_followup_enabled=False
        ),
        store,
        Mock(enabled_for=Mock(return_value=True)),
        messenger,
        Mock(
            can_access=AsyncMock(return_value=True),
            has_member=AsyncMock(return_value=True),
        ),
    )
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    calls: list[str] = []
    original = sqlite_storage.SqliteDatabase._run_transaction

    def blocked(
        database: sqlite_storage.SqliteDatabase,
        operation: Callable[[sqlite3.Connection], Any],
    ) -> Any:
        calls.append(operation.__name__)
        if not release.is_set():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(timeout=5)
        return original(database, operation)

    monkeypatch.setattr(sqlite_storage.SqliteDatabase, "_run_transaction", blocked)
    pending = asyncio.create_task(
        service.send_followup(conversation, actor, scheduler=Mock())
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        await service.send_followup(conversation, actor, scheduler=Mock())
        assert len(calls) == 1
        messenger.send.assert_not_awaited()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert await store.list_all() == [reminder]
        await service.send_followup(conversation, actor, scheduler=Mock())
        messenger.send.assert_awaited_once()
        assert await store.list_all() == []
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("stage", ["sent", "advance", "left"])
async def test_old_followup_cannot_remove_or_advance_new_join(
    tmp_path: Path, platform: Platform, stage: str
) -> None:
    conversation = ConversationRef(platform, "group", "group-1", "bot-1")
    actor = ActorRef(platform, "member-1", "member", "group-1", "bot-1")
    now = datetime.now(timezone.utc)
    old = TeamAuditPendingReminder(
        conversation, actor, now - timedelta(days=2), now - timedelta(days=1)
    )
    new = TeamAuditPendingReminder(conversation, actor, now, now + timedelta(days=1))
    store = SqliteTeamAuditReminderStore(
        tmp_path / "audit.sqlite", spawn=asyncio.create_task
    )
    await store.save(old)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def send(*_args: object, **_kwargs: object) -> SendResult:
        entered.set()
        await release.wait()
        return SendResult(delivered=True, message_id="sent")

    async def has_member(*_args: object, **_kwargs: object) -> bool:
        if stage == "left":
            entered.set()
            await release.wait()
            return False
        return True

    messenger = Mock(send=AsyncMock(side_effect=send))
    scheduler = Mock()
    service = TeamAuditService(
        TeamAuditWelcomeConfig(
            enabled=True,
            followup_enabled=True,
            final_followup_enabled=stage == "advance",
        ),
        store,
        Mock(enabled_for=Mock(return_value=True)),
        messenger,
        Mock(
            can_access=AsyncMock(return_value=True),
            has_member=AsyncMock(side_effect=has_member),
        ),
    )
    pending = asyncio.create_task(
        service.send_followup(conversation, actor, scheduler=scheduler)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        await store.save(new)
        release.set()
        await pending
        assert await store.get(conversation, actor) == new
        scheduler.add_job.assert_not_called()
        if stage == "left":
            messenger.send.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("starting", [False, True])
@pytest.mark.parametrize("restart", [False, True])
async def test_stop_during_storage_read_does_not_recreate_audit_jobs(
    *, starting: bool, restart: bool
) -> None:
    conversation = ConversationRef(Platform.ONEBOT, "group", "456")
    actor = ActorRef(Platform.ONEBOT, "101", "member", "456")
    now = datetime.now(timezone.utc)
    reminder = TeamAuditPendingReminder(
        conversation, actor, now, now + timedelta(hours=24)
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    reads = 0

    async def read() -> list[TeamAuditPendingReminder]:
        nonlocal reads
        reads += 1
        if reads > 1:
            return []
        entered.set()
        await release.wait()
        return [reminder]

    store = Mock(list_all=AsyncMock(side_effect=read))
    scheduler = Mock(get_jobs=Mock(return_value=[]))
    service = TeamAuditService(
        TeamAuditWelcomeConfig(enabled=True, followup_enabled=True),
        store,
        Mock(),
        Mock(),
        Mock(),
    )
    pending = asyncio.create_task(
        service.start(scheduler=scheduler)
        if starting
        else service.schedule_pending(scheduler)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        service.stop(scheduler=scheduler)
        if restart:
            await service.start(scheduler=scheduler)
        expected_calls = list(scheduler.add_job.call_args_list)
        release.set()
        await pending
        assert scheduler.add_job.call_args_list == expected_calls
        store.transition.assert_not_called()
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
