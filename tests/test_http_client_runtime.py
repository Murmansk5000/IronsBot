from collections.abc import Callable

import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

try:
    nonebot.load_plugin("ironsbot.plugins.http_client")
except RuntimeError as e:
    if "Plugin already exists" not in str(e):
        raise

from ironsbot.plugins.http_client import runtime as http_client_runtime


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


def test_http_client_runtime_setup_registers_lifecycle_once() -> None:
    http_client_runtime._http_client_runtime_state["registered"] = False
    driver = FakeDriver()

    http_client_runtime._setup_http_client_runtime(driver)
    http_client_runtime._setup_http_client_runtime(driver)

    assert len(driver.startup_handlers) == 1
    assert len(driver.shutdown_handlers) == 1
