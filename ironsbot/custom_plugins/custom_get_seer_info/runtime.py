# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Any

from nonebot import get_driver, logger, require

from .config import get_local_rank_config

_local_rank_scheduler_runtime_state = {"registered": False}


async def _scheduled_local_rank_refresh() -> None:
    from .commands._local_rank_refresh import refresh_local_rank_cache

    if not get_local_rank_config().auto_refresh:
        return

    result = await refresh_local_rank_cache()
    logger.info(
        "local rank cache auto refresh finished: "
        f"total={result.total}, "
        f"success={result.success}, "
        f"skipped_full={result.skipped_full}, "
        f"failed={result.failed}"
    )


def register_local_rank_refresh_job(scheduler: Any) -> None:
    local_rank_config = get_local_rank_config()
    scheduler.add_job(
        _scheduled_local_rank_refresh,
        "cron",
        hour=local_rank_config.refresh_hour,
        minute=local_rank_config.refresh_minute,
        id="custom_get_seer_info_local_rank_refresh",
        replace_existing=True,
    )


def _setup_local_rank_scheduler_runtime(driver: Any, scheduler: Any) -> None:
    if _local_rank_scheduler_runtime_state["registered"]:
        return

    @driver.on_startup
    async def _register_local_rank_refresh_job_on_startup() -> None:
        register_local_rank_refresh_job(scheduler)

    _local_rank_scheduler_runtime_state["registered"] = True


def setup_local_rank_scheduler_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_local_rank_scheduler_runtime(get_driver(), scheduler)


__all__ = ["setup_local_rank_scheduler_runtime"]
