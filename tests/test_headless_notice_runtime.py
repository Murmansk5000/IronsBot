from collections.abc import Callable

from pytest import MonkeyPatch

from ironsbot.plugins.headless_seer_notice import (
    runtime as headless_notice_runtime,
)


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


def test_headless_notice_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    registered_checks: list[tuple[str, object]] = []
    monkeypatch.setitem(
        headless_notice_runtime._headless_notice_runtime_state,
        "registered",
        registered_state,
    )
    monkeypatch.setattr(
        headless_notice_runtime,
        "register_startup_check",
        lambda name, check: registered_checks.append((name, check)),
    )
    driver = FakeDriver()
    scheduler = object()

    headless_notice_runtime._setup_headless_notice_runtime(driver, scheduler)
    headless_notice_runtime._setup_headless_notice_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1
    assert registered_checks == [
        ("headless_seer_login", headless_notice_runtime._startup_check)
    ]
