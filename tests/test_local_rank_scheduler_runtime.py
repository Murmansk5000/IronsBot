import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import nonebot

from ironsbot.config.models.settings import Settings
from ironsbot.integrations.headless_seer.client import ClientManager

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

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
    PlayerQueryConfig,
    RankPageRefreshConfig,
)
from ironsbot.integrations.storage.local_rank import SqliteLocalRankRepository
from ironsbot.plugins.seer import runtime as seer_runtime
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.seer.local_rank import LocalRankService
from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from ironsbot.services.seer.rank import RankService

TEST_CONFIG = Settings()
TEST_RUNTIME = build_test_runtime(feature_config=TEST_CONFIG.features)
HEADLESS = HeadlessService(
    ClientManager(TEST_RUNTIME.tasks.create),
    TEST_CONFIG.operations.headless,
    TEST_CONFIG.operations.headless_notice,
    TEST_RUNTIME.admin_notices,
)
RANK = cast("RankService", object())


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


class FakeHeadless:
    def get_game(self) -> object:
        return object()


class FakeRefreshService:
    def __init__(self, config: object, result: object) -> None:
        self.config = config
        self._result = result
        self.background_calls: list[bool] = []

    async def refresh(self, _game: object, *, background: bool = False) -> object:
        self.background_calls.append(background)
        return self._result


def test_register_local_rank_refresh_job_uses_standard_scheduler_fields(
    tmp_path: Path,
) -> None:
    scheduler = FakeScheduler()
    config = LocalRankConfig(
        path=tmp_path / "local-rank.sqlite",
        refresh_hour=3,
        refresh_minute=30,
    )
    service = LocalRankService(
        SqliteLocalRankRepository(config.path, config.max_players),
        config,
        PlayerQueryConfig(),
        RANK,
    )

    seer_runtime.register_local_rank_refresh_job(scheduler, HEADLESS, service)

    assert scheduler.jobs == [
        {
            "func": seer_runtime._scheduled_local_rank_refresh,
            "trigger": "cron",
            "id": "seer_local_rank_refresh",
            "replace_existing": True,
            "args": [HEADLESS, service],
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
    service = RankPageRefreshService(config, RANK)

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


def test_scheduled_refreshes_use_background_priority() -> None:
    async def run() -> None:
        headless = FakeHeadless()
        local = FakeRefreshService(
            SimpleNamespace(auto_refresh=True),
            SimpleNamespace(total=1, success=1, skipped_full=0, failed=0),
        )
        pages = FakeRefreshService(
            SimpleNamespace(enabled=True, active_start="", active_end=""),
            SimpleNamespace(total=1, success=1, failed=0),
        )

        await seer_runtime._scheduled_local_rank_refresh(
            cast("Any", headless),
            cast("Any", local),
        )
        await seer_runtime._scheduled_rank_page_refresh(
            cast("Any", headless),
            cast("Any", pages),
        )

        assert local.background_calls == [True]
        assert pages.background_calls == [True]

    asyncio.run(run())
