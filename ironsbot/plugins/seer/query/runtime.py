# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Any

from nonebot import get_driver, logger, require

from .config import get_local_rank_config, get_rank_query_config

_local_rank_scheduler_runtime_state = {"registered": False}
_render_crash_report_runtime_state = {"registered": False}


async def _scheduled_local_rank_refresh() -> None:
    from ironsbot.services.seer.local_rank_refresh import refresh_local_rank_cache

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
        id="seer_local_rank_refresh",
        replace_existing=True,
    )


async def _scheduled_rank_page_refresh() -> None:
    from ironsbot.services.seer.rank_page_refresh import refresh_rank_page_cache

    rank_config = get_rank_query_config().page_refresh
    if not rank_config.enabled:
        return

    result = await refresh_rank_page_cache()
    logger.info(
        "rank page cache auto refresh finished: "
        f"total={result.total}, success={result.success}, failed={result.failed}"
    )


def register_rank_page_refresh_jobs(scheduler: Any) -> None:
    rank_config = get_rank_query_config().page_refresh
    if not rank_config.enabled:
        return

    for refresh_time in rank_config.times:
        hour_text, minute_text = refresh_time.split(":", maxsplit=1)
        scheduler.add_job(
            _scheduled_rank_page_refresh,
            "cron",
            hour=int(hour_text),
            minute=int(minute_text),
            id=f"seer_rank_page_refresh_{hour_text}{minute_text}",
            replace_existing=True,
        )


def _setup_local_rank_scheduler_runtime(driver: Any, scheduler: Any) -> None:
    if _local_rank_scheduler_runtime_state["registered"]:
        return

    @driver.on_startup
    async def _register_local_rank_refresh_job_on_startup() -> None:
        register_local_rank_refresh_job(scheduler)
        register_rank_page_refresh_jobs(scheduler)

    _local_rank_scheduler_runtime_state["registered"] = True


def setup_local_rank_scheduler_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_local_rank_scheduler_runtime(get_driver(), scheduler)


def _setup_render_crash_report_runtime(driver: Any) -> None:
    if _render_crash_report_runtime_state["registered"]:
        return

    from ironsbot.services.seer.render_crash_report import (
        report_previous_render_crash,
    )

    driver.on_bot_connect(report_previous_render_crash)
    _render_crash_report_runtime_state["registered"] = True


def setup_render_crash_report_runtime() -> None:
    _setup_render_crash_report_runtime(get_driver())


__all__ = [
    "setup_local_rank_scheduler_runtime",
    "setup_render_crash_report_runtime",
]
