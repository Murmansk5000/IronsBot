from __future__ import annotations

import asyncio
import sqlite3
import threading
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.core.inbound_claims import InboundMessageKey
from ironsbot.core.platform import Platform
from ironsbot.integrations.storage import sqlite as sqlite_storage
from ironsbot.integrations.storage.inbound_claims import (
    _MIGRATIONS,
    SqliteInboundMessageClaims,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.inbound_claims import MemoryInboundMessageClaims

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.inbound_claims import InboundMessageClaims

KEY = InboundMessageKey(Platform.QQ_OFFICIAL, "app-a", "group", "group-a", "message")
CONVERSATION_SCOPED_VERSION = 2


@pytest.fixture(params=["memory", "sqlite"])
def claims(request: pytest.FixtureRequest, tmp_path: Path) -> InboundMessageClaims:
    if request.param == "memory":
        return MemoryInboundMessageClaims()
    return SqliteInboundMessageClaims(
        tmp_path / "claims.sqlite", spawn=asyncio.create_task
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        {"platform": Platform.ONEBOT},
        {"account_id": "app-b"},
        {"conversation_kind": "private"},
        {"conversation_id": "group-b"},
        {"message_id": "another"},
    ],
)
async def test_transport_claim_key_preserves_all_namespaces(
    claims: InboundMessageClaims, changed: dict[str, object]
) -> None:
    assert await claims.claim(KEY)
    assert not await claims.claim(KEY)
    assert await claims.claim(replace(KEY, **changed))
    assert not await claims.claim(KEY)


@pytest.mark.asyncio
async def test_concurrent_delivery_has_one_winner(claims: InboundMessageClaims) -> None:
    results = await asyncio.gather(*(claims.claim(KEY) for _ in range(8)))
    assert results.count(True) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_claim_expires_at_retention_boundary(
    tmp_path: Path, backend: str
) -> None:
    now = 100.0
    claims = (
        MemoryInboundMessageClaims(retention_seconds=10, clock=lambda: now)
        if backend == "memory"
        else SqliteInboundMessageClaims(
            tmp_path / "claims.sqlite", 10, lambda: now, spawn=asyncio.create_task
        )
    )
    assert await claims.claim(KEY)
    now = 109.0
    assert not await claims.claim(KEY)
    now = 110.0
    assert await claims.claim(KEY)


@pytest.mark.asyncio
async def test_persistent_claims_survive_service_restart(tmp_path: Path) -> None:
    path = tmp_path / "claims.sqlite"
    assert await SqliteInboundMessageClaims(path, spawn=asyncio.create_task).claim(KEY)
    assert not await SqliteInboundMessageClaims(path, spawn=asyncio.create_task).claim(
        KEY
    )
    assert await SqliteInboundMessageClaims(path, spawn=asyncio.create_task).claim(
        replace(KEY, platform=Platform.ONEBOT)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancelled_claim_waits_for_committed_connection_to_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: Platform,
    *,
    shutdown: bool,
) -> None:
    owner = TaskOwner()
    claims = SqliteInboundMessageClaims(
        tmp_path / "claims.sqlite", spawn=owner.create_draining
    )
    await claims.claim(replace(KEY, message_id="initialize"))
    entered = asyncio.Event()
    release = threading.Event()
    closed = threading.Event()
    loop = asyncio.get_running_loop()

    class Connection(sqlite3.Connection):
        def commit(self) -> None:
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(timeout=5)
            super().commit()

        def close(self) -> None:
            super().close()
            closed.set()

    def connect(path: str | Path) -> sqlite3.Connection:
        return sqlite3.connect(path, factory=Connection)

    monkeypatch.setattr(sqlite_storage, "open_sqlite_connection", connect)
    key = replace(KEY, platform=platform)
    closed_resources: list[bool] = []

    def close_resource() -> None:
        assert closed.is_set()
        closed_resources.append(True)

    lifecycle = ApplicationLifecycle(
        task_owner=owner,
        resource_shutdown_hooks=(("resource", close_resource),),
    )
    pending = owner.create(claims.claim(key), name="input_claim")
    closing: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        if shutdown:
            closing = asyncio.create_task(lifecycle.shutdown())
        for _ in range(2):
            pending.cancel()
            await asyncio.sleep(0)
            assert not pending.done()
        assert not closed.is_set()
        assert not closed_resources
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert closed.is_set()
        if closing is not None:
            await asyncio.wait_for(closing, timeout=3)
            assert closed_resources == [True]
            assert not owner.tasks
        restarted = SqliteInboundMessageClaims(claims.path, spawn=asyncio.create_task)
        assert not await restarted.claim(key)
    finally:
        release.set()
        await asyncio.gather(
            pending, *([closing] if closing is not None else []), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_memory_capacity_evicts_only_oldest_claim() -> None:
    claims = MemoryInboundMessageClaims(capacity=1)
    assert await claims.claim(KEY)
    assert await claims.claim(replace(KEY, message_id="another"))
    assert await claims.claim(KEY)


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [1, CONVERSATION_SCOPED_VERSION])
async def test_existing_official_claims_are_migrated_without_allowing_replay(
    tmp_path: Path, version: int
) -> None:
    path = tmp_path / "claims.sqlite"
    legacy = SqliteDatabase(
        path,
        migrations=_MIGRATIONS[:version],
        migration_namespace="qq_official_inbound_claims",
    )
    with legacy.connect() as connection:
        columns = "app_id, event_type, message_id, claimed_at"
        values: tuple[object, ...] = (
            KEY.account_id,
            "GROUP_MESSAGE",
            KEY.message_id,
            100,
        )
        if version == CONVERSATION_SCOPED_VERSION:
            columns += ", conversation_id"
            values += (KEY.conversation_id,)
        connection.execute(
            f"INSERT INTO qq_official_inbound_claims ({columns}) "
            f"VALUES ({', '.join('?' for _ in values)})",
            values,
        )
    claims = SqliteInboundMessageClaims(
        path, clock=lambda: 101, spawn=asyncio.create_task
    )
    assert not await claims.claim(KEY)
    assert await claims.claim(replace(KEY, platform=Platform.ONEBOT))
    assert await claims.claim(replace(KEY, conversation_id="another")) is (
        version == CONVERSATION_SCOPED_VERSION
    )
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "inbound_message_claims" in names
        assert "qq_official_inbound_claims" not in names
