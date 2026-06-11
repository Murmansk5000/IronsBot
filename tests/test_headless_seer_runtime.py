from collections.abc import Callable

from ironsbot.plugins import headless_seer


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []
        self.shutdown_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler

    def on_shutdown(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.shutdown_handlers.append(handler)
        return handler


def test_headless_seer_runtime_setup_registers_lifecycle_once() -> None:
    headless_seer._headless_seer_runtime_state["registered"] = False
    driver = FakeDriver()

    headless_seer._setup_headless_seer_runtime(driver)
    headless_seer._setup_headless_seer_runtime(driver)

    assert len(driver.startup_handlers) == 1
    assert len(driver.shutdown_handlers) == 1
