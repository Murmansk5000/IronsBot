from collections.abc import Callable
from types import SimpleNamespace

import nonebot
from pytest import MonkeyPatch

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.custom_plugins import activity_reminder


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


def test_activity_reminder_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        activity_reminder._activity_reminder_runtime_state,
        "registered",
        registered_state,
    )
    monkeypatch.setitem(
        activity_reminder._activity_reminder_runtime_state,
        "scheduler",
        None,
    )
    driver = FakeDriver()
    scheduler = object()

    activity_reminder._setup_activity_reminder_runtime(driver, scheduler)
    activity_reminder._setup_activity_reminder_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1
    assert activity_reminder._activity_reminder_runtime_state["scheduler"] is scheduler


def test_register_activity_reminder_jobs_installs_startup_and_daily_scans(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        activity_reminder,
        "get_activity_config",
        lambda: SimpleNamespace(enabled=True),
    )

    activity_reminder.register_activity_reminder_jobs(scheduler)

    assert [job["id"] for job in scheduler.jobs] == [
        "activity_reminder_startup_scan",
        "activity_reminder_daily_scan",
    ]


def test_load_activity_rows_resolves_session_factory_at_runtime(
    monkeypatch: MonkeyPatch,
) -> None:
    session_factory = object()
    calls: list[tuple[object, str, bool]] = []

    def fake_load_activity_rows(
        raw_session_factory: object,
        *,
        database_name: str,
        only_shown: bool,
    ) -> list[dict[str, int]]:
        calls.append((raw_session_factory, database_name, only_shown))
        return [{"id": 1}]

    monkeypatch.setattr(
        activity_reminder,
        "_activity_db_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        activity_reminder,
        "get_activity_config",
        lambda: SimpleNamespace(only_shown=False),
    )
    monkeypatch.setattr(
        activity_reminder,
        "load_activity_rows",
        fake_load_activity_rows,
    )

    assert activity_reminder._load_activity_rows() == [{"id": 1}]
    assert calls == [(session_factory, activity_reminder.SEERAPI_DB_NAME, False)]
