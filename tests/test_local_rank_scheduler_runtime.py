from collections.abc import Callable

import nonebot
from pytest import MonkeyPatch

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

try:
    nonebot.load_plugin("nonebot_plugin_htmlkit")
except RuntimeError as e:
    if "Plugin already exists" not in str(e):
        raise

from ironsbot.custom_plugins.custom_get_seer_info.commands import (
    _local_rank_scheduler,
)


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


def test_local_rank_scheduler_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        _local_rank_scheduler._local_rank_scheduler_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = object()

    _local_rank_scheduler._setup_local_rank_scheduler_runtime(driver, scheduler)
    _local_rank_scheduler._setup_local_rank_scheduler_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1
