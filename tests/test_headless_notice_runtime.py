from collections.abc import Callable

from pytest import MonkeyPatch

from ironsbot.config.models.runtime import HeadlessNoticeConfig
from ironsbot.plugins.headless_seer_notice import (
    runtime as headless_notice_runtime,
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


def test_register_reconnect_checks_uses_standard_scheduler_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        headless_notice_runtime,
        "get_headless_notice_config",
        lambda: HeadlessNoticeConfig(reconnect_check_times="00:01,00:02"),
    )

    headless_notice_runtime._register_reconnect_checks(scheduler)

    assert scheduler.jobs == [
        {
            "func": headless_notice_runtime._daily_reconnect_check,
            "trigger": "cron",
            "id": "headless_reconnect_check:00:01",
            "replace_existing": True,
            "args": ["00:01"],
            "hour": 0,
            "minute": 1,
            "second": 0,
            "timezone": "Asia/Shanghai",
        },
        {
            "func": headless_notice_runtime._daily_reconnect_check,
            "trigger": "cron",
            "id": "headless_reconnect_check:00:02",
            "replace_existing": True,
            "args": ["00:02"],
            "hour": 0,
            "minute": 2,
            "second": 0,
            "timezone": "Asia/Shanghai",
        },
    ]
