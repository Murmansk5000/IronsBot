import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.dependencies.utils import get_typed_signature

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.core.platform import BotAccountRef, Platform
from ironsbot.integrations.nonebot_host import NoneBotHostBinding

if TYPE_CHECKING:
    from nonebot.internal.driver import Driver


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[..., object]] = []
        self.shutdown_handlers: list[Callable[..., object]] = []
        self.bot_connect_handlers: list[Callable[..., object]] = []
        self.bot_disconnect_handlers: list[Callable[..., object]] = []

    def on_startup(self, handler: Callable[..., object]) -> Callable[..., object]:
        self.startup_handlers.append(handler)
        return handler

    def on_shutdown(self, handler: Callable[..., object]) -> Callable[..., object]:
        self.shutdown_handlers.append(handler)
        return handler

    def on_bot_connect(
        self,
        handler: Callable[..., object],
    ) -> Callable[..., object]:
        self.bot_connect_handlers.append(handler)
        return handler

    def on_bot_disconnect(
        self,
        handler: Callable[..., object],
    ) -> Callable[..., object]:
        self.bot_disconnect_handlers.append(handler)
        return handler


class _ResourceUnavailableError(RuntimeError):
    pass


def test_host_installs_only_startup_and_shutdown_hooks_once() -> None:
    driver = FakeDriver()
    lifecycle = ApplicationLifecycle()
    binding = NoneBotHostBinding(
        cast("Driver", driver), lifecycle
    )

    binding.install()
    binding.install()

    assert len(driver.startup_handlers) == 1
    assert len(driver.shutdown_handlers) == 1
    assert driver.bot_connect_handlers == []
    assert driver.bot_disconnect_handlers == []
    connect_signature = get_typed_signature(lifecycle.bot_connect)
    disconnect_signature = get_typed_signature(lifecycle.bot_disconnect)
    assert connect_signature.parameters["account"].annotation is BotAccountRef
    assert disconnect_signature.parameters["account"].annotation is BotAccountRef


def test_lifecycle_runs_sync_and_async_hooks_in_lifecycle_order() -> None:
    calls: list[str] = []

    def first() -> None:
        calls.append("first")

    async def second() -> None:
        calls.append("second")

    lifecycle = ApplicationLifecycle(
        startup_hooks=(("first", first), ("second", second)),
        shutdown_hooks=(("first", first), ("second", second)),
    )

    asyncio.run(lifecycle.startup())
    asyncio.run(lifecycle.shutdown())

    assert calls == ["first", "second", "second", "first"]


def test_lifecycle_starts_resources_before_contributions() -> None:
    calls: list[str] = []
    lifecycle = ApplicationLifecycle(
        resource_startup_hooks=(("resource", lambda: calls.append("resource")),),
        startup_hooks=(("plugin", lambda: calls.append("plugin")),),
    )

    asyncio.run(lifecycle.startup())

    assert calls == ["resource", "plugin"]


def test_resource_startup_failure_prevents_application_startup() -> None:
    calls: list[str] = []

    async def failing_resource() -> None:
        calls.append("resource")
        raise _ResourceUnavailableError

    lifecycle = ApplicationLifecycle(
        resource_startup_hooks=(("resource", failing_resource),),
        startup_hooks=(("plugin", lambda: calls.append("plugin")),),
    )

    with pytest.raises(_ResourceUnavailableError):
        asyncio.run(lifecycle.startup())

    assert calls == ["resource"]


def test_lifecycle_cancels_tasks_before_resources() -> None:
    async def run() -> None:
        calls: list[str] = []
        owner = TaskOwner()

        async def background() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                calls.append("task")

        def close_resource() -> None:
            calls.append("resource")

        task = owner.create(background(), name="test-background")
        await asyncio.sleep(0)
        lifecycle = ApplicationLifecycle(
            task_owner=owner,
            resource_shutdown_hooks=(("resource", close_resource),),
        )
        await lifecycle.shutdown()

        assert task.cancelled()
        assert calls == ["task", "resource"]

    asyncio.run(run())


def test_lifecycle_isolates_hook_failure() -> None:
    calls: list[str] = []

    async def failing() -> None:
        calls.append("failing")
        raise RuntimeError("boom")

    async def healthy() -> None:
        calls.append("healthy")

    lifecycle = ApplicationLifecycle(
        startup_hooks=(("failing", failing), ("healthy", healthy)),
    )

    asyncio.run(lifecycle.startup())

    assert calls == ["failing", "healthy"]


def test_lifecycle_tracks_connected_bots_and_runs_connection_hooks() -> None:
    calls: list[tuple[str, BotAccountRef]] = []

    async def on_connect(account: BotAccountRef) -> None:
        calls.append(("connect", account))

    async def on_disconnect(account: BotAccountRef) -> None:
        calls.append(("disconnect", account))

    lifecycle = ApplicationLifecycle(
        bot_connect_hooks=(("connect", on_connect),),
        bot_disconnect_hooks=(("disconnect", on_disconnect),),
    )
    bot = BotAccountRef(Platform.ONEBOT, "123456")

    asyncio.run(lifecycle.startup())
    asyncio.run(lifecycle.bot_connect(bot))
    assert lifecycle.connected_accounts == {bot}

    asyncio.run(lifecycle.bot_disconnect(bot))
    assert lifecycle.connected_accounts == set()
    assert calls == [("connect", bot), ("disconnect", bot)]


def test_lifecycle_runs_first_connection_hooks_only_once() -> None:
    calls: list[str] = []

    async def on_first_connect(_bot: BotAccountRef) -> None:
        calls.append("first")

    async def on_connect(_bot: BotAccountRef) -> None:
        calls.append("connect")

    lifecycle = ApplicationLifecycle(
        first_bot_connect_hooks=(("first", on_first_connect),),
        bot_connect_hooks=(("connect", on_connect),),
    )
    bot = BotAccountRef(Platform.ONEBOT, "123456")

    asyncio.run(lifecycle.startup())
    asyncio.run(lifecycle.bot_connect(bot))
    asyncio.run(lifecycle.bot_disconnect(bot))
    asyncio.run(lifecycle.bot_connect(bot))

    assert calls == ["first", "connect", "connect"]


@pytest.mark.asyncio
async def test_ready_observations_wait_for_contribution_startup() -> None:
    calls: list[str] = []
    account = BotAccountRef(Platform.QQ_OFFICIAL, "opaque-app")

    async def resource() -> None:
        calls.append("resource")
        await lifecycle.bot_connect(account)
        assert calls == ["resource"]

    lifecycle = ApplicationLifecycle(
        resource_startup_hooks=(("resource", resource),),
        startup_hooks=(("plugin", lambda: calls.append("plugin")),),
        first_bot_connect_hooks=(("first", lambda _: calls.append("first")),),
        bot_connect_hooks=(("connected", lambda _: calls.append("connected")),),
    )
    await lifecycle.startup()

    assert calls == ["resource", "plugin"]
    await asyncio.gather(*tuple(lifecycle.task_owner.tasks))
    assert calls == ["resource", "plugin", "first", "connected"]
    assert lifecycle.connected_accounts == {account}
    await lifecycle.shutdown()


@pytest.mark.asyncio
async def test_transient_ready_during_startup_does_not_trigger_business() -> None:
    calls: list[BotAccountRef] = []
    lifecycle = ApplicationLifecycle(
        first_bot_connect_hooks=(("first", calls.append),),
    )
    transient = BotAccountRef(Platform.QQ_OFFICIAL, "transient-app")
    ready = BotAccountRef(Platform.QQ_OFFICIAL, "ready-app")
    await lifecycle.bot_connect(transient)
    await lifecycle.bot_disconnect(transient)
    await lifecycle.startup()
    assert not lifecycle.connected_accounts
    assert not calls
    await lifecycle.bot_connect(ready)
    assert calls == [ready]
    await lifecycle.shutdown()


@pytest.mark.asyncio
async def test_failed_startup_discards_queued_ready_and_late_callbacks() -> None:
    calls: list[BotAccountRef] = []
    account = BotAccountRef(Platform.QQ_OFFICIAL, "failed-app")

    async def fail() -> None:
        await lifecycle.bot_connect(account)
        raise _ResourceUnavailableError

    lifecycle = ApplicationLifecycle(
        resource_startup_hooks=(("fail", fail),),
        first_bot_connect_hooks=(("first", calls.append),),
    )
    with pytest.raises(_ResourceUnavailableError):
        await lifecycle.startup()
    await lifecycle.bot_connect(account)
    assert not calls
    assert not lifecycle.connected_accounts
    assert not lifecycle._pending_connections


@pytest.mark.asyncio
async def test_connection_identity_keeps_platform_scope_and_stops_after_shutdown() -> (
    None
):
    connected: list[BotAccountRef] = []
    disconnected: list[BotAccountRef] = []
    lifecycle = ApplicationLifecycle(
        bot_connect_hooks=(("connect", connected.append),),
        bot_disconnect_hooks=(("disconnect", disconnected.append),),
    )
    onebot = BotAccountRef(Platform.ONEBOT, "same-id")
    official = BotAccountRef(Platform.QQ_OFFICIAL, "same-id")
    await lifecycle.startup()
    await lifecycle.bot_connect(onebot)
    await lifecycle.bot_connect(official)
    assert lifecycle.connected_accounts == {onebot, official}
    await lifecycle.bot_disconnect(onebot)
    assert lifecycle.connected_accounts == {official}
    await lifecycle.shutdown()
    await lifecycle.bot_connect(onebot)
    await lifecycle.bot_disconnect(official)
    assert not lifecycle.connected_accounts
    assert connected == [onebot, official]
    assert disconnected == [onebot]


@pytest.mark.asyncio
async def test_concurrent_ready_uses_selected_platform_for_first_hooks() -> None:
    first: list[BotAccountRef] = []
    lifecycle = ApplicationLifecycle(
        first_bot_connect_hooks=(("first", first.append),),
        first_connection_platforms=frozenset({Platform.QQ_OFFICIAL}),
    )
    await lifecycle.startup()
    helper = BotAccountRef(Platform.ONEBOT, "helper")
    await lifecycle.bot_connect(helper)
    assert not first
    accounts = tuple(BotAccountRef(Platform.QQ_OFFICIAL, f"app-{n}") for n in range(2))
    await asyncio.gather(*(lifecycle.bot_connect(account) for account in accounts))
    assert len(first) == 1
    assert first[0] in accounts
    assert lifecycle.connected_accounts == {helper, *accounts}
    await lifecycle.shutdown()


@pytest.mark.asyncio
async def test_no_outbound_platform_does_not_run_first_connection_business() -> None:
    first: list[BotAccountRef] = []
    lifecycle = ApplicationLifecycle(
        first_bot_connect_hooks=(("first", first.append),),
        first_connection_platforms=frozenset(),
    )
    await lifecycle.startup()
    for platform in Platform:
        await lifecycle.bot_connect(BotAccountRef(platform, "account"))
    assert len(lifecycle.connected_accounts) == len(Platform)
    assert not first
    await lifecycle.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_deferred_first_connection_work_is_owned_and_cancelled_before_resources(
    platform: Platform,
) -> None:
    started = asyncio.Event()
    calls: list[str] = []
    account = BotAccountRef(platform, "account")

    async def initialize() -> None:
        await lifecycle.bot_connect(account)

    async def first(_account: BotAccountRef) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            calls.append("cancelled")

    lifecycle = ApplicationLifecycle(
        resource_startup_hooks=(("initialize", initialize),),
        resource_shutdown_hooks=(("close", lambda: calls.append("closed")),),
        first_bot_connect_hooks=(("first", first),),
    )
    await lifecycle.startup()
    await asyncio.wait_for(started.wait(), timeout=1)
    assert lifecycle.task_owner.tasks
    await lifecycle.shutdown()
    assert calls == ["cancelled", "closed"]
    assert not lifecycle.task_owner.tasks
