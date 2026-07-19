# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from nonebot import logger

from ironsbot.core.time import daily_time_parts
from ironsbot.services.operations.scheduler import JobRegistry

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
JOB_ID = "scheduled_bot_restart"

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


async def _scheduled_restart(
    scheduled_time: str,
    grace_seconds: float,
    restart_process: Callable[[], Awaitable[None]],
) -> None:
    if grace_seconds > 0:
        logger.warning(
            "scheduled bot restart {} will signal process in {:.1f}s",
            scheduled_time,
            grace_seconds,
        )
        await asyncio.sleep(grace_seconds)

    await restart_process()


def register_restart_jobs(
    scheduler: Any,
    *,
    restart_times: tuple[str, ...],
    grace_seconds: float,
    restart_process: Callable[[], Awaitable[None]],
) -> None:
    if not restart_times:
        logger.info("scheduled bot restart disabled")
        return

    registry = JobRegistry(scheduler, prefix=f"{JOB_ID}:")
    for scheduled_time in restart_times:
        hour, minute = daily_time_parts(scheduled_time)
        registry.add(
            _scheduled_restart,
            "cron",
            job_id=scheduled_time,
            args=[scheduled_time, grace_seconds, restart_process],
            hour=hour,
            minute=minute,
            second=0,
            timezone=LOCAL_TZ,
        )

    logger.info(
        "scheduled bot restart registered: "
        "times={}",
        ", ".join(restart_times),
    )
