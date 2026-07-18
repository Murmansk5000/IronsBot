import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from nonebot.adapters.onebot.v11 import Bot
from nonebot.internal.driver import Driver

from ironsbot.app.lifecycle import ApplicationLifecycle


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


@dataclass(frozen=True, slots=True)
class FakeBot:
    self_id: int


def fake_driver() -> Driver:
    return cast("Driver", FakeDriver())


def test_lifecycle_installs_exactly_four_driver_hooks_once() -> None:
    driver = FakeDriver()
    installed: list[str] = []
    lifecycle = ApplicationLifecycle(
        cast("Driver", driver),
        installers=(("test", lambda: installed.append("test")),),
    )

    lifecycle.install()
    lifecycle.install()

    assert installed == ["test"]
    assert len(driver.startup_handlers) == 1
    assert len(driver.shutdown_handlers) == 1
    assert len(driver.bot_connect_handlers) == 1
    assert len(driver.bot_disconnect_handlers) == 1


def test_lifecycle_runs_startup_in_order_and_shutdown_in_reverse() -> None:
    calls: list[str] = []

    async def first() -> None:
        calls.append("first")

    async def second() -> None:
        calls.append("second")

    lifecycle = ApplicationLifecycle(
        fake_driver(),
        startup_hooks=(("first", first), ("second", second)),
        shutdown_hooks=(("first", first), ("second", second)),
    )

    asyncio.run(lifecycle.startup())
    asyncio.run(lifecycle.shutdown())

    assert calls == ["first", "second", "second", "first"]


def test_lifecycle_isolates_hook_failure() -> None:
    calls: list[str] = []

    async def failing() -> None:
        calls.append("failing")
        raise RuntimeError("boom")

    async def healthy() -> None:
        calls.append("healthy")

    lifecycle = ApplicationLifecycle(
        fake_driver(),
        startup_hooks=(("failing", failing), ("healthy", healthy)),
    )

    asyncio.run(lifecycle.startup())

    assert calls == ["failing", "healthy"]


def test_lifecycle_tracks_connected_bots_and_runs_connection_hooks() -> None:
    calls: list[tuple[str, int]] = []

    async def on_connect(bot: Bot) -> None:
        calls.append(("connect", int(bot.self_id)))

    async def on_disconnect(bot: Bot) -> None:
        calls.append(("disconnect", int(bot.self_id)))

    lifecycle = ApplicationLifecycle(
        fake_driver(),
        bot_connect_hooks=(("connect", on_connect),),
        bot_disconnect_hooks=(("disconnect", on_disconnect),),
    )
    bot = cast("Bot", FakeBot(self_id=123456))

    asyncio.run(lifecycle.bot_connect(bot))
    assert lifecycle.connected_bot_ids == {123456}

    asyncio.run(lifecycle.bot_disconnect(bot))
    assert lifecycle.connected_bot_ids == set()
    assert calls == [("connect", 123456), ("disconnect", 123456)]


def test_lifecycle_runs_first_connection_hooks_only_once() -> None:
    calls: list[str] = []

    async def on_first_connect(_bot: Bot) -> None:
        calls.append("first")

    async def on_connect(_bot: Bot) -> None:
        calls.append("connect")

    lifecycle = ApplicationLifecycle(
        fake_driver(),
        first_bot_connect_hooks=(("first", on_first_connect),),
        bot_connect_hooks=(("connect", on_connect),),
    )
    bot = cast("Bot", FakeBot(self_id=123456))

    asyncio.run(lifecycle.bot_connect(bot))
    asyncio.run(lifecycle.bot_disconnect(bot))
    asyncio.run(lifecycle.bot_connect(bot))

    assert calls == ["first", "connect", "connect"]
