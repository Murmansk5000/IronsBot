from __future__ import annotations

import asyncio
import sqlite3
import threading
from typing import TYPE_CHECKING

import pytest

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.integrations.storage import sqlite as sqlite_storage
from ironsbot.integrations.storage.identity_links import SqliteIdentityLinkStore
from ironsbot.services.identity_linking import IdentityLinkingService, OfficialAccount
from ironsbot.services.identity_mutations import IdentityMutationCoordinator
from ironsbot.services.identity_principals import IdentityPrincipalService

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.identity_link_store import CrossPlatformIdentityLink


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["confirm", "revoke_onebot", "revoke_official"])
@pytest.mark.parametrize("shutdown", [False, True])
async def test_commit_publishes_before_cancel(  # noqa: PLR0915 - real lifecycle replay
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, *, shutdown: bool
) -> None:
    owner = TaskOwner()
    store = SqliteIdentityLinkStore(
        tmp_path / "state.sqlite", spawn=owner.create_draining
    )
    principals = IdentityPrincipalService()
    published: list[str] = []

    def link(value: CrossPlatformIdentityLink) -> None:
        principals.register_identity_link(value)
        published.append("linked")

    def unlink(value: CrossPlatformIdentityLink) -> None:
        principals.unregister_identity_link(value)
        published.append("unlinked")

    service = IdentityLinkingService(
        store,
        {"test": OfficialAccount("test", "app")},
        mutations=IdentityMutationCoordinator(owner.create_draining),
        on_link=link,
        on_unlink=unlink,
    )
    onebot = ActorRef(Platform.ONEBOT, "101")
    official = ActorRef(Platform.QQ_OFFICIAL, "member", "member", "group", "app")
    token = (await service.begin(onebot)).token
    if operation != "confirm":
        await service.confirm(official, token)
        published.clear()
    entered, release, committed = _block_commits(monkeypatch)

    async def change() -> None:
        if operation == "confirm":
            await service.confirm(official, token)
        else:
            await service.revoke(onebot if operation == "revoke_onebot" else official)

    closed_resources: list[bool] = []

    def close_resource() -> None:
        assert published == (["linked"] if operation == "confirm" else ["unlinked"])
        closed_resources.append(True)

    lifecycle = ApplicationLifecycle(
        task_owner=owner,
        resource_shutdown_hooks=(("resource", close_resource),),
    )
    pending = owner.create(change(), name="identity_change")
    closing: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        if shutdown:
            closing = asyncio.create_task(lifecycle.shutdown())
        else:
            pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        assert not closed_resources
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        if closing is not None:
            await asyncio.wait_for(closing, timeout=3)
            assert closed_resources == [True]
            assert not owner.tasks
        assert committed.is_set()
        assert published == (["linked"] if operation == "confirm" else ["unlinked"])
        assert (principals.actor_principal(official).kind == "qq") is (
            operation == "confirm"
        )
        restored = SqliteIdentityLinkStore(store.path, spawn=asyncio.create_task)
        assert bool(await restored.all_links()) is (operation == "confirm")
    finally:
        release.set()
        await asyncio.gather(
            pending, *([closing] if closing is not None else []), return_exceptions=True
        )


def _block_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[asyncio.Event, threading.Event, threading.Event]:
    entered = asyncio.Event()
    release = threading.Event()
    committed = threading.Event()
    loop = asyncio.get_running_loop()

    class Connection(sqlite3.Connection):
        def commit(self) -> None:
            writing = self.in_transaction
            if writing:
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(timeout=5)
            super().commit()
            if writing:
                committed.set()

    def connect(path: str | Path) -> sqlite3.Connection:
        return sqlite3.connect(path, factory=Connection)

    monkeypatch.setattr(sqlite_storage, "open_sqlite_connection", connect)
    return entered, release, committed


@pytest.mark.asyncio
async def test_queued_mutation_cancels_without_releasing_an_accepted_change() -> None:
    mutations = IdentityMutationCoordinator(asyncio.create_task)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def first() -> None:
        entered.set()
        await release.wait()
        calls.append("published")

    async def queued() -> None:
        calls.append("cancelled_queue_ran")

    async def last() -> None:
        calls.append("next")

    pending = asyncio.create_task(mutations.run(first))
    waiting: asyncio.Task[None] | None = None
    next_change: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        waiting = asyncio.create_task(mutations.run(queued))
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        pending.cancel()
        next_change = asyncio.create_task(mutations.run(last))
        await asyncio.sleep(0)
        assert not pending.done()
        assert calls == []
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await next_change
        assert calls == ["published", "next"]
    finally:
        release.set()
        await asyncio.gather(
            pending,
            *[task for task in (waiting, next_change) if task is not None],
            return_exceptions=True,
        )
