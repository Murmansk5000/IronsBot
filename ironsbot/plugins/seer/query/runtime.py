# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from nonebot import logger

from ironsbot.integrations.scheduler.jobs import JobRegistry

from .config import get_local_rank_config, get_rank_query_config

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService

SEER_QUERY_JOB_PREFIX = "seer_"


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


async def _scheduled_local_rank_refresh(headless: HeadlessService) -> None:
    from ironsbot.services.seer.local_rank_refresh import refresh_local_rank_cache

    if not get_local_rank_config().auto_refresh:
        return

    result = await refresh_local_rank_cache(headless.get_game())
    logger.info(
        "local rank cache auto refresh finished: "
        f"total={result.total}, "
        f"success={result.success}, "
        f"skipped_full={result.skipped_full}, "
        f"failed={result.failed}"
    )


def register_local_rank_refresh_job(
    scheduler: Any, headless: HeadlessService
) -> None:
    local_rank_config = get_local_rank_config()
    JobRegistry(scheduler, prefix=SEER_QUERY_JOB_PREFIX).add(
        _scheduled_local_rank_refresh,
        "cron",
        args=[headless],
        hour=local_rank_config.refresh_hour,
        minute=local_rank_config.refresh_minute,
        job_id="local_rank_refresh",
    )


async def _scheduled_rank_page_refresh(headless: HeadlessService) -> None:
    from ironsbot.services.seer.rank_page_refresh import refresh_rank_page_cache

    rank_config = get_rank_query_config().page_refresh
    if not rank_config.enabled:
        return
    if not _is_rank_page_refresh_active(rank_config):
        logger.info("rank page cache auto refresh skipped: outside active window")
        return

    result = await refresh_rank_page_cache(headless.get_game())
    logger.info(
        "rank page cache auto refresh finished: "
        f"total={result.total}, success={result.success}, failed={result.failed}"
    )


def register_rank_page_refresh_jobs(
    scheduler: Any, headless: HeadlessService
) -> None:
    rank_config = get_rank_query_config().page_refresh
    if not rank_config.enabled:
        return

    registry = JobRegistry(scheduler, prefix=SEER_QUERY_JOB_PREFIX)
    if rank_config.interval_minutes > 0:
        minute_pattern = (
            f"{rank_config.interval_offset_minutes}/{rank_config.interval_minutes}"
        )
        registry.add(
            _scheduled_rank_page_refresh,
            "cron",
            args=[headless],
            minute=minute_pattern,
            jitter=rank_config.schedule_jitter_seconds,
            job_id="rank_page_refresh_interval",
        )

    for refresh_time in rank_config.times:
        hour_text, minute_text = refresh_time.split(":", maxsplit=1)
        registry.add(
            _scheduled_rank_page_refresh,
            "cron",
            args=[headless],
            hour=int(hour_text),
            minute=int(minute_text),
            jitter=rank_config.schedule_jitter_seconds,
            job_id=f"rank_page_refresh_{hour_text}{minute_text}",
        )


__all__ = [
    "register_local_rank_refresh_job",
    "register_rank_page_refresh_jobs",
]
