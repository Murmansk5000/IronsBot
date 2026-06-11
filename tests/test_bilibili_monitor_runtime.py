from collections.abc import Callable

from pytest import MonkeyPatch

from ironsbot.custom_plugins.bilibili_monitor import service


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
        service._bilibili_monitor_runtime_state,
        "registered",
        registered_state,
    )
    monkeypatch.setattr(
        service,
        "register_startup_check",
        lambda name, check: registered_checks.append((name, check)),
    )
    driver = FakeDriver()
    scheduler = object()

    service._setup_bilibili_monitor_runtime(driver, scheduler)
    service._setup_bilibili_monitor_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1
    assert registered_checks == [("bilibili_monitor", service._startup_check)]
