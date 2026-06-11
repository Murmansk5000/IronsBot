from collections.abc import Callable

from pytest import MonkeyPatch

from ironsbot.custom_plugins import scheduled_restart


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


def test_scheduled_restart_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        scheduled_restart._scheduled_restart_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = object()

    scheduled_restart._setup_scheduled_restart_runtime(driver, scheduler)
    scheduled_restart._setup_scheduled_restart_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1
