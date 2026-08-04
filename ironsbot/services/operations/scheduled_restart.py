# SPDX-License-Identifier: MIT
"""Scheduled process-restart use case and scheduler registration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from ironsbot.core.time import daily_time_parts
from ironsbot.services.operations.scheduler import JobRegistry, Scheduler

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
JOB_ID = "scheduled_bot_restart"
logger = logging.getLogger(__name__)

ProcessRestart = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ScheduledRestartService:
    restart_times: tuple[str, ...]
    grace_seconds: float
    restart_process: ProcessRestart

    def register_jobs(self, scheduler: Scheduler) -> None:
        if not self.restart_times:
            logger.info("scheduled bot restart disabled")
            return

        registry = JobRegistry(scheduler, prefix=f"{JOB_ID}:")
        for scheduled_time in self.restart_times:
            hour, minute = daily_time_parts(scheduled_time)
            registry.add(
                _scheduled_restart,
                "cron",
                job_id=scheduled_time,
                args=[scheduled_time, self.grace_seconds, self.restart_process],
                hour=hour,
                minute=minute,
                second=0,
                timezone=LOCAL_TZ,
            )

        logger.info(
            "scheduled bot restart registered: times=%s",
            ", ".join(self.restart_times),
        )


async def _scheduled_restart(
    scheduled_time: str,
    grace_seconds: float,
    restart_process: ProcessRestart,
) -> None:
    if grace_seconds > 0:
        logger.warning(
            "scheduled bot restart %s will signal process in %.1fs",
            scheduled_time,
            grace_seconds,
        )
        await asyncio.sleep(grace_seconds)

    await restart_process()
