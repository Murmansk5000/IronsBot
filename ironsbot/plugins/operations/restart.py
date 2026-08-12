# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from nonebot import logger

from ironsbot.core.time import scheduled_clock_time
from ironsbot.services.operations.scheduler import JobRegistry

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
        clock_time = scheduled_clock_time(
            scheduled_time,
            error_message="operations.restart.times must contain daily HH:MM:SS times",
        )
        registry.add_daily(
            _scheduled_restart,
            job_id=str(clock_time),
            args=[scheduled_time, grace_seconds, restart_process],
            clock_time=clock_time,
        )

    logger.info(
        "scheduled bot restart registered: "
        "times={}",
        ", ".join(restart_times),
    )
