# SPDX-License-Identifier: GPL-3.0-or-later
"""Register Seer rank refresh jobs with the application scheduler."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ironsbot.core.platform import reference_digest
from ironsbot.core.time import scheduled_clock_time, second_of_day
from ironsbot.services.operations.scheduler import JobRegistry

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService

SEER_QUERY_JOB_PREFIX = "seer_"
logger = logging.getLogger(__name__)


def _is_rank_page_refresh_active(rank_config: Any, now: datetime | None = None) -> bool:
    if not rank_config.active_start or not rank_config.active_end:
        return True

    current_time = now or datetime.now(timezone.utc).astimezone()
    current = (current_time.hour * 60 + current_time.minute) * 60 + current_time.second
    start = second_of_day(
        rank_config.active_start,
        error_message="invalid active start",
    )
    end = second_of_day(rank_config.active_end, error_message="invalid active end")
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


async def _scheduled_local_rank_refresh(
    headless: HeadlessService,
    service: LocalRankService,
) -> None:
    config = service.config
    if not config.auto_refresh:
        return

    result = await service.refresh(headless.get_game, background=True)
    logger.info(
        "local rank cache auto refresh finished: "
        f"total={result.total}, "
        f"success={result.success}, "
        f"skipped_full={result.skipped_full}, "
        f"failed={result.failed}"
    )


def register_local_rank_refresh_job(
    scheduler: Any,
    headless: HeadlessService,
    service: LocalRankService,
) -> None:
    config = service.config
    clock_time = scheduled_clock_time(config.time, error_message="invalid refresh time")
    JobRegistry(scheduler, prefix=SEER_QUERY_JOB_PREFIX).add_daily(
        _scheduled_local_rank_refresh,
        clock_time=clock_time,
        args=[headless, service],
        job_id="local_rank_refresh",
    )


async def _scheduled_rank_page_refresh(
    headless: HeadlessService,
    service: RankPageRefreshService,
) -> None:
    config = service.config
    if not config.enabled:
        return
    if not _is_rank_page_refresh_active(config):
        logger.info("rank page cache auto refresh skipped: outside active window")
        return

    parallelism = headless.healthy_worker_count
    if parallelism <= 0:
        logger.info("rank page cache auto refresh skipped: no healthy worker")
        return

    result = await service.refresh(
        headless.get_game,
        background=True,
        max_parallelism=parallelism,
    )
    workers = (
        ",".join(
            f"{reference_digest(str(user_id))}:{count}"
            for user_id, count in sorted(result.worker_page_counts.items())
        )
        or "none"
    )
    logger.info(
        "rank page cache auto refresh finished: "
        f"total={result.total}, success={result.success}, failed={result.failed}, "
        f"parallelism={result.parallelism}, workers={workers}"
    )


def register_rank_page_refresh_jobs(
    scheduler: Any,
    headless: HeadlessService,
    service: RankPageRefreshService,
) -> None:
    config = service.config
    if not config.enabled:
        return

    registry = JobRegistry(scheduler, prefix=SEER_QUERY_JOB_PREFIX)
    if config.interval_minutes > 0:
        minute_pattern = f"{config.interval_offset_minutes}/{config.interval_minutes}"
        registry.add(
            _scheduled_rank_page_refresh,
            "cron",
            args=[headless, service],
            minute=minute_pattern,
            jitter=config.schedule_jitter_seconds,
            job_id="rank_page_refresh_interval",
        )

    for refresh_time in config.times:
        clock_time = scheduled_clock_time(
            refresh_time,
            error_message="invalid rank page refresh time",
        )
        registry.add_daily(
            _scheduled_rank_page_refresh,
            clock_time=clock_time,
            args=[headless, service],
            jitter=config.schedule_jitter_seconds,
            job_id=(
                "rank_page_refresh_"
                f"{clock_time.hour:02d}{clock_time.minute:02d}{clock_time.second:02d}"
            ),
        )
