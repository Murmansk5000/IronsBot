from collections.abc import Callable

import nonebot
from pytest import MonkeyPatch

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.messaging import runtime


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


def test_message_actions_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        runtime._message_actions_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = object()

    runtime._setup_message_actions_runtime(driver, scheduler)
    runtime._setup_message_actions_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1
