from __future__ import annotations

import asyncio
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.app.lifecycle import ApplicationLifecycle
from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import BotAccountRef, Platform
from ironsbot.integrations.onebot.connections import OneBotConnections
from ironsbot.integrations.onebot.execution_identity import (
    OneBotExecutionIdentityResolver,
)
from ironsbot.integrations.onebot.transport import OneBotTransport
from ironsbot.integrations.onebot.websocket_session import OneBotWebSocketSession


def _bot(account_id: str = "111") -> OneBotWebSocketSession:
    return OneBotWebSocketSession(account_id, AsyncMock(), timeout=1)


def test_connections_are_application_owned_and_replace_by_session() -> None:
    first, second = OneBotConnections(), OneBotConnections()
    old, current, other = _bot(), _bot(), _bot("222")
    first.connect(old)
    second.connect(other)
    first.connect(current)
    assert first.get("111") is current
    assert second.get("111") is None
    assert not first.disconnect(old)
    assert first.get("111") is current
    assert first.disconnect(current)
    assert first.snapshot() == ()
    assert second.snapshot() == (other,)
    second.clear()
    assert second.snapshot() == ()


def test_connection_snapshot_prefers_receiving_account_without_mutating_order() -> None:
    connections = OneBotConnections()
    first, second = _bot(), _bot("222")
    connections.connect(first)
    connections.connect(second)
    assert connections.snapshot(preferred_id="222") == (second, first)
    assert connections.snapshot() == (first, second)


def test_connection_directory_import_does_not_initialize_nonebot() -> None:
    script = """
import importlib.abc
import sys
class RejectNoneBot(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'nonebot' or fullname.startswith('nonebot.'):
            raise AssertionError('unexpected framework import: ' + fullname)
sys.meta_path.insert(0, RejectNoneBot())
from ironsbot.integrations.onebot.connections import OneBotConnections
connections = OneBotConnections()
assert connections.get('111') is None
assert connections.snapshot() == ()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_transport_publishes_before_business_and_ignores_stale_disconnect() -> (
    None
):
    connections = OneBotConnections()
    disconnected = AsyncMock()
    seen: list[OneBotWebSocketSession] = []

    async def connected(account: BotAccountRef) -> None:
        assert account.platform is Platform.ONEBOT
        connection = connections.get(account.id)
        assert isinstance(connection, OneBotWebSocketSession)
        seen.append(connection)

    lifecycle = ApplicationLifecycle(
        bot_connect_hooks=(("observer", connected),),
        bot_disconnect_hooks=(("observer", disconnected),),
        resource_shutdown_hooks=(("connections", connections.clear),),
    )
    transport = OneBotTransport(
        cast(
            "Any",
            SimpleNamespace(config=SimpleNamespace(model_dump=dict, api_timeout=1)),
        ),
        spawn=lifecycle.task_owner.create,
        connections=connections,
        observer=lifecycle,
        received=AsyncMock(),
        notices=AsyncMock(),
        request_http=AsyncMock(),
    )
    await lifecycle.startup()
    old, current = _bot(), _bot()
    transport._connected(old)
    await asyncio.gather(*tuple(transport.tasks))
    transport._connected(current)
    await asyncio.gather(*tuple(transport.tasks))
    assert seen == [old, current]
    transport._disconnected(old)
    assert connections.get("111") is current
    account = BotAccountRef(Platform.ONEBOT, "111")
    assert lifecycle.connected_accounts == {account}
    disconnected.assert_not_awaited()
    transport._disconnected(current)
    await asyncio.gather(*tuple(transport.tasks))
    assert connections.get("111") is None
    assert lifecycle.connected_accounts == set()
    disconnected.assert_awaited_once_with(account)
    transport._connected(current)
    await asyncio.gather(*tuple(transport.tasks))
    await transport.close()
    await lifecycle.shutdown()
    assert connections.snapshot() == ()


@pytest.mark.asyncio
async def test_execution_names_are_local_and_replaced_with_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections = OneBotConnections()
    old, current = _bot(), _bot()
    lookup = AsyncMock(side_effect=[{"nickname": "first"}, {"nickname": "second"}])
    monkeypatch.setattr(OneBotWebSocketSession, "call_api", lookup)
    resolver = OneBotExecutionIdentityResolver(connections, lambda _: "configured")
    identity = ExecutionIdentity(Platform.ONEBOT, "111")
    connections.connect(old)
    assert (await resolver.resolve(identity)).display_name == "first"
    assert (await resolver.resolve(identity)).display_name == "first"
    assert lookup.await_count == 1
    isolated = OneBotExecutionIdentityResolver(
        OneBotConnections(), lambda _: "isolated"
    )
    assert (await isolated.resolve(identity)).display_name == "isolated"
    connections.connect(current)
    assert (await resolver.resolve(identity)).display_name == "second"
    assert lookup.await_count == len((old, current))
    connections.disconnect(current)
    assert (await resolver.resolve(identity)).display_name == "configured"


@pytest.mark.asyncio
async def test_late_nickname_lookup_cannot_publish_previous_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections = OneBotConnections()
    old, current = _bot(), _bot()
    entered, release = asyncio.Event(), asyncio.Event()

    async def lookup(*args: object, **kwargs: object) -> dict[str, str]:
        del args, kwargs
        entered.set()
        await release.wait()
        return {"nickname": "obsolete"}

    monkeypatch.setattr(OneBotWebSocketSession, "call_api", lookup)
    connections.connect(old)
    resolver = OneBotExecutionIdentityResolver(connections, lambda _: "configured")
    task = asyncio.create_task(
        resolver.resolve(ExecutionIdentity(Platform.ONEBOT, "111"))
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        connections.connect(current)
        release.set()
        assert (await task).display_name == "configured"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_other_platform_identity_never_queries_onebot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = AsyncMock(side_effect=AssertionError("unexpected API call"))
    monkeypatch.setattr(OneBotWebSocketSession, "call_api", lookup)
    resolver = OneBotExecutionIdentityResolver(OneBotConnections(), str)
    identity = ExecutionIdentity(Platform.QQ_OFFICIAL, "app")
    assert await resolver.resolve(identity) is identity
    lookup.assert_not_awaited()
