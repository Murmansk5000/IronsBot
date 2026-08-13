# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from nonebot import logger

from ironsbot.core.time import clock_window_contains, scheduled_clock_time
from ironsbot.services.operations.scheduler import JobRegistry

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService

SEER_QUERY_JOB_PREFIX = "seer_"


def _is_rank_page_refresh_active(rank_config: Any, now: datetime | None = None) -> bool:
    if not rank_config.active_start or not rank_config.active_end:
        return True

    current_time = now or datetime.now(timezone.utc).astimezone()
    return clock_window_contains(
        current_time,
        start=rank_config.active_start,
        end=rank_config.active_end,
        error_message=(
            "seer.rank.page_refresh active_start/active_end must be HH:MM:SS times"
        ),
    )


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
    clock_time = scheduled_clock_time(
        config.time,
        error_message="seer.local_rank.time must use HH:MM:SS",
    )
    JobRegistry(scheduler, prefix=SEER_QUERY_JOB_PREFIX).add_daily(
        _scheduled_local_rank_refresh,
        args=[headless, service],
        clock_time=clock_time,
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
    workers = ",".join(
        f"{user_id}:{count}"
        for user_id, count in sorted(result.worker_page_counts.items())
    ) or "none"
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
        registry.add_wall_clock_interval(
            _scheduled_rank_page_refresh,
            args=[headless, service],
            minutes=config.interval_minutes,
            offset_minutes=config.interval_offset_minutes,
            offset_seconds=config.interval_offset_seconds,
            jitter=config.schedule_jitter_seconds,
            job_id="rank_page_refresh_interval",
        )

    for refresh_time in config.times:
        clock_time = scheduled_clock_time(
            refresh_time,
            error_message=(
                "seer.rank.page_refresh.times must contain daily HH:MM:SS times"
            ),
        )
        registry.add_daily(
            _scheduled_rank_page_refresh,
            args=[headless, service],
            clock_time=clock_time,
            jitter=config.schedule_jitter_seconds,
            job_id=f"rank_page_refresh_{str(clock_time).replace(':', '')}",
        )
