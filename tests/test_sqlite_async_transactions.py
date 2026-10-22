from __future__ import annotations

import asyncio
import sqlite3
import threading
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.integrations.storage import sqlite as storage
from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration

if TYPE_CHECKING:
    from pathlib import Path

_FAILURE_MESSAGE = "operation failed"


@pytest.fixture
def database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SqliteDatabase, list[tuple[str, int]]]:
    events: list[tuple[str, int]] = []

    class Connection(sqlite3.Connection):
        def commit(self) -> None:
            events.append(("commit", threading.get_ident()))
            super().commit()

        def rollback(self) -> None:
            events.append(("rollback", threading.get_ident()))
            super().rollback()

        def close(self) -> None:
            super().close()
            events.append(("closed", threading.get_ident()))

    def open_connection(path: str | Path) -> sqlite3.Connection:
        events.append(("open", threading.get_ident()))
        connection = sqlite3.connect(path, factory=Connection)
        connection.set_trace_callback(
            lambda _sql: events.append(("sql", threading.get_ident()))
        )
        return connection

    monkeypatch.setattr(storage, "open_sqlite_connection", open_connection)
    return SqliteDatabase(
        tmp_path / "state.sqlite",
        migrations=(SqliteMigration(1, ("CREATE TABLE sample (value INTEGER)",)),),
        spawn=asyncio.create_task,
    ), events


@pytest.mark.asyncio
async def test_complete_sqlite_transaction_uses_one_worker_thread(
    database: tuple[SqliteDatabase, list[tuple[str, int]]],
) -> None:
    db, events = database
    loop_thread = threading.get_ident()

    def operation(connection: sqlite3.Connection) -> int:
        connection.execute("INSERT INTO sample VALUES (1)")
        return int(connection.execute("SELECT count(*) FROM sample").fetchone()[0])

    assert await db.run_transaction(operation) == 1
    assert {label for label, _thread in events} >= {"open", "sql", "commit", "closed"}
    assert len({thread for _label, thread in events}) == 1
    assert all(thread != loop_thread for _label, thread in events)


@pytest.mark.asyncio
async def test_sqlite_worker_rolls_back_failed_callback(
    database: tuple[SqliteDatabase, list[tuple[str, int]]],
) -> None:
    db, events = database

    def fail(connection: sqlite3.Connection) -> None:
        connection.execute("INSERT INTO sample VALUES (1)")
        raise RuntimeError(_FAILURE_MESSAGE)

    with pytest.raises(RuntimeError, match="operation failed"):
        await db.run_transaction(fail)
    assert "rollback" in [label for label, _thread in events]
    assert events[-1][0] == "closed"
    assert (
        await db.run_transaction(
            lambda conn: conn.execute("SELECT * FROM sample").fetchall()
        )
        == []
    )
    assert (
        await db.run_transaction(
            lambda conn: conn.execute("PRAGMA integrity_check").fetchone()[0]
        )
        == "ok"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_repeated_cancel_drains_transaction_without_blocking_loop(
    database: tuple[SqliteDatabase, list[tuple[str, int]]], *, fail: bool
) -> None:
    db, events = database
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()

    def operation(connection: sqlite3.Connection) -> None:
        connection.execute("INSERT INTO sample VALUES (1)")
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=5)
        if fail:
            raise RuntimeError(_FAILURE_MESSAGE)

    pending = asyncio.create_task(db.run_transaction(operation))
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        for _ in range(2):
            pending.cancel()
            await asyncio.sleep(0)
            assert not pending.done()
        await asyncio.wait_for(asyncio.sleep(0), timeout=1)
        assert "closed" not in [label for label, _thread in events]
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert events[-1][0] == "closed"
        rows = await db.run_transaction(
            lambda conn: conn.execute("SELECT * FROM sample").fetchall()
        )
        assert rows == ([] if fail else [(1,)])
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_before_transaction_submission_opens_no_connection(
    database: tuple[SqliteDatabase, list[tuple[str, int]]],
) -> None:
    db, events = database
    pending = asyncio.create_task(
        db.run_transaction(lambda conn: conn.execute("SELECT 1").fetchone())
    )
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert events == []


@pytest.mark.asyncio
async def test_async_transaction_requires_an_explicit_task_owner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unowned.sqlite"
    with pytest.raises(RuntimeError, match="owned task spawner"):
        await SqliteDatabase(path).run_transaction(
            lambda conn: conn.execute("SELECT 1")
        )
    assert not path.exists()


@pytest.mark.asyncio
async def test_application_shutdown_drains_submitted_transaction_before_resources(
    database: tuple[SqliteDatabase, list[tuple[str, int]]],
) -> None:

    original, events = database
    owner = TaskOwner()
    db = replace(original, spawn=owner.create_draining)
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    closed_resources: list[bool] = []

    def operation(connection: sqlite3.Connection) -> None:
        connection.execute("INSERT INTO sample VALUES (1)")
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=5)

    def close_resource() -> None:
        assert events[-1][0] == "closed"
        closed_resources.append(True)

    lifecycle = ApplicationLifecycle(
        task_owner=owner,
        resource_shutdown_hooks=(("resource", close_resource),),
    )
    writing = owner.create(db.run_transaction(operation), name="state_write")
    closing: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        closing = asyncio.create_task(lifecycle.shutdown())
        await asyncio.sleep(0)
        assert not writing.done()
        assert not closing.done()
        assert not closed_resources
        release.set()
        await asyncio.wait_for(closing, timeout=3)
        assert writing.cancelled()
        assert closed_resources == [True]
        assert not owner.tasks
        rows = await original.run_transaction(
            lambda conn: conn.execute("SELECT * FROM sample").fetchall()
        )
        assert rows == [(1,)]
    finally:
        release.set()
        await asyncio.gather(
            writing, *([closing] if closing is not None else []), return_exceptions=True
        )
