from collections.abc import Callable

from pytest import MonkeyPatch

from ironsbot.custom_plugins.bilibili_monitor import runtime as bili_runtime


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


def test_bilibili_monitor_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    registered_checks: list[tuple[str, object]] = []
    monkeypatch.setitem(
        bili_runtime._bilibili_monitor_runtime_state,
        "registered",
        registered_state,
    )
    monkeypatch.setattr(
        bili_runtime,
        "register_startup_check",
        lambda name, check: registered_checks.append((name, check)),
    )
    driver = FakeDriver()
    scheduler = object()

    bili_runtime._setup_bilibili_monitor_runtime(driver, scheduler)
    bili_runtime._setup_bilibili_monitor_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1
    assert registered_checks == [("bilibili_monitor", bili_runtime._startup_check)]
