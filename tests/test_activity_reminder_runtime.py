from collections.abc import Callable

import nonebot
from pytest import MonkeyPatch

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.custom_plugins import activity_reminder


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


def test_activity_reminder_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        activity_reminder._activity_reminder_runtime_state,
        "registered",
        registered_state,
    )
    monkeypatch.setitem(
        activity_reminder._activity_reminder_runtime_state,
        "scheduler",
        None,
    )
    driver = FakeDriver()
    scheduler = object()

    activity_reminder._setup_activity_reminder_runtime(driver, scheduler)
    activity_reminder._setup_activity_reminder_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1
    assert activity_reminder._activity_reminder_runtime_state["scheduler"] is scheduler
