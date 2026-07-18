import os
from pathlib import Path

import nonebot

from ironsbot.app.composition import build_headless_service
from ironsbot.config.loader import clear_app_config_cache
from ironsbot.config.models.app import AppConfig

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")
clear_app_config_cache()

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

try:
    nonebot.load_plugin("nonebot_plugin_htmlkit")
except RuntimeError as e:
    if "Plugin already exists" not in str(e):
        raise

from ironsbot.config.models.secrets import CredentialsConfig
from ironsbot.config.models.seer import (
    LocalRankConfig,
    RankPageRefreshConfig,
)
from ironsbot.plugins.seer.query import runtime as seer_runtime
from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService
from tests.helpers.runtime import build_test_runtime

TEST_CONFIG = AppConfig()
TEST_RUNTIME = build_test_runtime(feature_config=TEST_CONFIG.feature)
HEADLESS = build_headless_service(
    TEST_CONFIG.runtime,
    CredentialsConfig(),
    TEST_RUNTIME.admin_notices,
)


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_register_local_rank_refresh_job_uses_standard_scheduler_fields(
) -> None:
    scheduler = FakeScheduler()
    config = LocalRankConfig(refresh_hour=3, refresh_minute=30)

    seer_runtime.register_local_rank_refresh_job(scheduler, HEADLESS, config)

    assert scheduler.jobs == [
        {
            "func": seer_runtime._scheduled_local_rank_refresh,
            "trigger": "cron",
            "id": "seer_local_rank_refresh",
            "replace_existing": True,
            "args": [HEADLESS, config],
            "hour": 3,
            "minute": 30,
        }
    ]


def test_register_rank_page_refresh_jobs_uses_standard_scheduler_fields(
) -> None:
    scheduler = FakeScheduler()
    config = RankPageRefreshConfig(
        enabled=True,
        interval_minutes=15,
        interval_offset_minutes=4,
        schedule_jitter_seconds=240,
        times=["01:15"],
    )
    service = RankPageRefreshService(config)

    seer_runtime.register_rank_page_refresh_jobs(scheduler, HEADLESS, service)

    assert scheduler.jobs == [
        {
            "func": seer_runtime._scheduled_rank_page_refresh,
            "trigger": "cron",
            "id": "seer_rank_page_refresh_interval",
            "replace_existing": True,
            "args": [HEADLESS, service],
            "minute": "4/15",
            "jitter": 240,
        },
        {
            "func": seer_runtime._scheduled_rank_page_refresh,
            "trigger": "cron",
            "id": "seer_rank_page_refresh_0115",
            "replace_existing": True,
            "args": [HEADLESS, service],
            "hour": 1,
            "minute": 15,
            "jitter": 240,
        },
    ]
