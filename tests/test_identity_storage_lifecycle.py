from __future__ import annotations

import asyncio
import sqlite3
import threading
from typing import TYPE_CHECKING

import pytest

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.integrations.storage import sqlite as sqlite_storage
from ironsbot.integrations.storage.identity_links import SqliteIdentityLinkStore
from ironsbot.services.identity_link_store import OfficialIdentity

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancelled_identity_write_waits_for_connection_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, group: bool, shutdown: bool
) -> None:
    owner = TaskOwner()
    store = SqliteIdentityLinkStore(
        tmp_path / "state.sqlite", spawn=owner.create_draining
    )
    await store.all_links()
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

    async def write() -> None:
        if group:
            await store.link_group_verified(
                onebot_group_id="group",
                official_app_id="app",
                official_group_openid="group-openid",
                now=100,
            )
        else:
            await store.link_verified(
                onebot_qq_id="member",
                official=OfficialIdentity(
                    "app", "member", "member-openid", "group-openid"
                ),
                now=100,
            )

    closed_resources: list[bool] = []

    def close_resource() -> None:
        assert closed.is_set()
        closed_resources.append(True)

    lifecycle = ApplicationLifecycle(
        task_owner=owner,
        resource_shutdown_hooks=(("resource", close_resource),),
    )
    pending = owner.create(write(), name="identity_write")
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
        restarted = SqliteIdentityLinkStore(store.path, spawn=asyncio.create_task)
        links = (
            await restarted.all_group_links() if group else await restarted.all_links()
        )
        assert len(links) == 1
    finally:
        release.set()
        await asyncio.gather(
            pending, *([closing] if closing is not None else []), return_exceptions=True
        )
