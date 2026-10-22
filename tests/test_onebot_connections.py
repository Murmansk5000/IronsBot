from __future__ import annotations

import asyncio
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Adapter, Bot

from ironsbot.app.lifecycle import ApplicationLifecycle
from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import BotAccountRef, Platform
from ironsbot.integrations.nonebot_lifecycle import NoneBotLifecycleBinding
from ironsbot.integrations.onebot.connections import OneBotConnections
from ironsbot.integrations.onebot.execution_identity import (
    OneBotExecutionIdentityResolver,
)


def _bot(account_id: str = "111") -> Bot:
    return Bot(Mock(spec=Adapter), account_id)


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
async def test_driver_hooks_publish_before_business_and_ignore_stale_disconnect() -> (
    None
):
    driver = Mock()
    connections = OneBotConnections()
    disconnected = AsyncMock()
    seen: list[Bot] = []

    async def connected(account: BotAccountRef) -> None:
        assert account.platform is Platform.ONEBOT
        connection = connections.get(account.id)
        assert isinstance(connection, Bot)
        seen.append(connection)

    lifecycle = ApplicationLifecycle(
        bot_connect_hooks=(("observer", connected),),
        bot_disconnect_hooks=(("observer", disconnected),),
        resource_shutdown_hooks=(("connections", connections.clear),),
    )
    NoneBotLifecycleBinding(driver, lifecycle, connections).install()
    await lifecycle.startup()
    connect = driver.on_bot_connect.call_args.args[0]
    disconnect = driver.on_bot_disconnect.call_args.args[0]
    old, current = _bot(), _bot()
    await connect(old)
    await connect(current)
    assert seen == [old, current]
    await disconnect(old)
    assert connections.get("111") is current
    account = BotAccountRef(Platform.ONEBOT, "111")
    assert lifecycle.connected_accounts == {account}
    disconnected.assert_not_awaited()
    await disconnect(current)
    assert connections.get("111") is None
    assert lifecycle.connected_accounts == set()
    disconnected.assert_awaited_once_with(account)
    await connect(current)
    await lifecycle.shutdown()
    assert connections.snapshot() == ()


@pytest.mark.asyncio
async def test_execution_names_are_local_and_replaced_with_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections = OneBotConnections()
    old, current = _bot(), _bot()
    lookup = AsyncMock(side_effect=[{"nickname": "first"}, {"nickname": "second"}])
    monkeypatch.setattr(Bot, "call_api", lookup)
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

    monkeypatch.setattr(Bot, "call_api", lookup)
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
    monkeypatch.setattr(Bot, "call_api", lookup)
    resolver = OneBotExecutionIdentityResolver(OneBotConnections(), str)
    identity = ExecutionIdentity(Platform.QQ_OFFICIAL, "app")
    assert await resolver.resolve(identity) is identity
    lookup.assert_not_awaited()
