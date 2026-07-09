from collections.abc import Callable

from pytest import MonkeyPatch

from ironsbot.config.models.runtime import RestartConfig
from ironsbot.plugins.scheduled_restart import (
    runtime as scheduled_restart_runtime,
)


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


def test_scheduled_restart_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        scheduled_restart_runtime._scheduled_restart_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = object()

    scheduled_restart_runtime._setup_scheduled_restart_runtime(driver, scheduler)
    scheduled_restart_runtime._setup_scheduled_restart_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1


def test_register_restart_job_uses_standard_scheduler_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        scheduled_restart_runtime,
        "get_restart_config",
        lambda: RestartConfig.model_validate(
            {
                "enabled": True,
                "times": ["04:30"],
                "grace_seconds": 0,
            }
        ),
    )

    scheduled_restart_runtime._register_restart_job(scheduler)

    assert scheduler.jobs == [
        {
            "func": scheduled_restart_runtime._scheduled_restart,
            "trigger": "cron",
            "id": "scheduled_bot_restart:04:30",
            "replace_existing": True,
            "args": ["04:30"],
            "hour": 4,
            "minute": 30,
            "second": 0,
            "timezone": scheduled_restart_runtime.LOCAL_TZ,
        }
    ]
