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

from ironsbot.config.models.seer import (
    LocalRankConfig,
    RankPageRefreshConfig,
    RankQueryConfig,
)
from ironsbot.plugins.seer.query import runtime as seer_runtime


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


def test_local_rank_scheduler_runtime_setup_registers_startup_once(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        seer_runtime._local_rank_scheduler_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = object()

    seer_runtime._setup_local_rank_scheduler_runtime(driver, scheduler)
    seer_runtime._setup_local_rank_scheduler_runtime(driver, scheduler)

    assert len(driver.startup_handlers) == 1


def test_register_local_rank_refresh_job_uses_standard_scheduler_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        seer_runtime,
        "get_local_rank_config",
        lambda: LocalRankConfig(refresh_hour=3, refresh_minute=30),
    )

    seer_runtime.register_local_rank_refresh_job(scheduler)

    assert scheduler.jobs == [
        {
            "func": seer_runtime._scheduled_local_rank_refresh,
            "trigger": "cron",
            "id": "seer_local_rank_refresh",
            "replace_existing": True,
            "hour": 3,
            "minute": 30,
        }
    ]


def test_register_rank_page_refresh_jobs_uses_standard_scheduler_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        seer_runtime,
        "get_rank_query_config",
        lambda: RankQueryConfig(
            page_refresh=RankPageRefreshConfig(
                enabled=True,
                interval_minutes=15,
                interval_offset_minutes=4,
                schedule_jitter_seconds=240,
                times=["01:15"],
            )
        ),
    )

    seer_runtime.register_rank_page_refresh_jobs(scheduler)

    assert scheduler.jobs == [
        {
            "func": seer_runtime._scheduled_rank_page_refresh,
            "trigger": "cron",
            "id": "seer_rank_page_refresh_interval",
            "replace_existing": True,
            "minute": "4/15",
            "jitter": 240,
        },
        {
            "func": seer_runtime._scheduled_rank_page_refresh,
            "trigger": "cron",
            "id": "seer_rank_page_refresh_0115",
            "replace_existing": True,
            "hour": 1,
            "minute": 15,
            "jitter": 240,
        },
    ]
