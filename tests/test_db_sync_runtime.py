import asyncio
from collections.abc import Callable
from types import SimpleNamespace

import nonebot
from pytest import MonkeyPatch

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

try:
    nonebot.load_plugin("ironsbot.plugins.db_sync")
except RuntimeError as e:
    if "Plugin already exists" not in str(e):
        raise

from ironsbot.plugins import db_sync
from ironsbot.plugins.db_sync import runtime as db_sync_runtime


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


def test_db_sync_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        db_sync_runtime._db_sync_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = FakeScheduler()

    db_sync_runtime._setup_db_sync_runtime(driver, scheduler)
    db_sync_runtime._setup_db_sync_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1


def test_register_database_defers_engine_and_scheduler_setup(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_engines: list[str] = []
    monkeypatch.setattr(db_sync, "_registered_syncs", {})
    monkeypatch.setattr(db_sync, "_registered_local_databases", {})
    monkeypatch.setattr(db_sync.db_manager, "register", registered_engines.append)

    db_sync.register_database(
        "unit",
        sync_url="https://example.invalid/unit.sqlite",
        sync_interval_minutes=15,
    )

    assert "unit" in db_sync._registered_syncs
    assert registered_engines == []


def test_db_sync_startup_prepares_engines_and_interval_jobs(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_engines: list[str] = []
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        db_sync,
        "_registered_syncs",
        {
            "unit": db_sync._SyncEntry(
                "https://example.invalid/unit.sqlite",
                15,
                None,
                None,
            )
        },
    )
    monkeypatch.setattr(db_sync, "_registered_local_databases", {})
    monkeypatch.setattr(db_sync, "_prepared_databases", set())
    monkeypatch.setattr(db_sync.db_manager, "register", registered_engines.append)
    monkeypatch.setattr(
        db_sync_runtime,
        "get_data_sync_config",
        lambda: SimpleNamespace(interval_enabled=True, on_startup=False),
    )

    asyncio.run(db_sync_runtime._start_db_sync_runtime(scheduler))

    assert registered_engines == ["unit"]
    assert scheduler.jobs == [
        {
            "func": db_sync.run_sync_database,
            "trigger": "interval",
            "args": ["unit"],
            "minutes": 15,
            "id": "db_sync_unit",
            "replace_existing": True,
        }
    ]
