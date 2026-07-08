import asyncio
from collections.abc import Callable

from pytest import MonkeyPatch

from ironsbot.plugins.bilibili import runtime as bili_runtime


class FakeDriver:
    def __init__(self) -> None:
        self.startup_handlers: list[Callable[[], object]] = []

    def on_startup(self, handler: Callable[[], object]) -> Callable[[], object]:
        self.startup_handlers.append(handler)
        return handler


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


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


def test_register_bili_auto_check_job_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()

    asyncio.run(bili_runtime.register_bili_auto_check_job(scheduler))

    assert scheduler.jobs == [
        {
            "func": bili_runtime.auto_check_job,
            "trigger": "interval",
            "id": "bilibili_monitor_auto_check",
            "replace_existing": True,
            "minutes": 1,
        }
    ]
