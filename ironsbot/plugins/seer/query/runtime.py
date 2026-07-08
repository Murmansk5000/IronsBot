# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nonebot import get_driver, logger, require

from ironsbot.shared.scheduler import add_or_replace_job

from .config import get_local_rank_config, get_rank_query_config

_local_rank_scheduler_runtime_state = {"registered": False}
_render_crash_report_runtime_state = {"registered": False}


def _minute_of_day(value: str) -> int:
    hour_text, minute_text = value.split(":", maxsplit=1)
    return int(hour_text) * 60 + int(minute_text)


def _is_rank_page_refresh_active(rank_config: Any, now: datetime | None = None) -> bool:
    if not rank_config.active_start or not rank_config.active_end:
        return True

    current_time = now or datetime.now(timezone.utc).astimezone()
    current = current_time.hour * 60 + current_time.minute
    start = _minute_of_day(rank_config.active_start)
    end = _minute_of_day(rank_config.active_end)
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


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
    add_or_replace_job(
        scheduler,
        _scheduled_local_rank_refresh,
        "cron",
        hour=local_rank_config.refresh_hour,
        minute=local_rank_config.refresh_minute,
        job_id="seer_local_rank_refresh",
    )


async def _scheduled_rank_page_refresh() -> None:
    from ironsbot.services.seer.rank_page_refresh import refresh_rank_page_cache

    rank_config = get_rank_query_config().page_refresh
    if not rank_config.enabled:
        return
    if not _is_rank_page_refresh_active(rank_config):
        logger.info("rank page cache auto refresh skipped: outside active window")
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

    if rank_config.interval_minutes > 0:
        minute_pattern = (
            f"{rank_config.interval_offset_minutes}/{rank_config.interval_minutes}"
        )
        add_or_replace_job(
            scheduler,
            _scheduled_rank_page_refresh,
            "cron",
            minute=minute_pattern,
            jitter=rank_config.schedule_jitter_seconds,
            job_id="seer_rank_page_refresh_interval",
        )

    for refresh_time in rank_config.times:
        hour_text, minute_text = refresh_time.split(":", maxsplit=1)
        add_or_replace_job(
            scheduler,
            _scheduled_rank_page_refresh,
            "cron",
            hour=int(hour_text),
            minute=int(minute_text),
            jitter=rank_config.schedule_jitter_seconds,
            job_id=f"seer_rank_page_refresh_{hour_text}{minute_text}",
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
