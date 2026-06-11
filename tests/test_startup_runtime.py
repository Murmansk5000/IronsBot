from collections.abc import Callable

from pytest import MonkeyPatch

from ironsbot.custom_plugins import startup_ready, startup_ready_runtime
from ironsbot.custom_plugins.startup_notice.runtime import (
    _setup_startup_notice_runtime,
    _startup_notice_runtime_state,
    send_startup_notice,
)


class FakeDriver:
    def __init__(self) -> None:
        self.bot_connect_handlers: list[Callable[[object], object]] = []

    def on_bot_connect(
        self,
        handler: Callable[[object], object],
    ) -> Callable[[object], object]:
        self.bot_connect_handlers.append(handler)
        return handler


def test_startup_ready_runtime_setup_registers_bot_connect_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        startup_ready_runtime._startup_ready_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()

    startup_ready_runtime._setup_startup_ready_runtime(driver)
    startup_ready_runtime._setup_startup_ready_runtime(driver)

    assert driver.bot_connect_handlers == [
        startup_ready.run_registered_startup_checks
    ]


def test_startup_notice_runtime_setup_registers_bot_connect_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        _startup_notice_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()

    _setup_startup_notice_runtime(driver)
    _setup_startup_notice_runtime(driver)

    assert driver.bot_connect_handlers == [send_startup_notice]
