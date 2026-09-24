# SPDX-License-Identifier: MIT
"""Scheduled process-restart use case and scheduler registration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from ironsbot.core.time import scheduled_clock_time
from ironsbot.services.operations.scheduler import JobRegistry, Scheduler

if TYPE_CHECKING:
    from ironsbot.services.operations.docker_update import DockerUpdateService

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
            clock_time = scheduled_clock_time(
                scheduled_time,
                error_message="invalid scheduled restart time",
            )
            registry.add_daily(
                _scheduled_restart,
                clock_time=clock_time,
                job_id=str(clock_time),
                args=[scheduled_time, self.grace_seconds, self.restart_process],
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


async def update_image_and_restart(
    docker_update: DockerUpdateService,
    fallback_restart: ProcessRestart,
) -> None:
    try:
        _message, action = await docker_update.prepare_update_and_restart()
        logger.info("scheduled Docker maintenance prepared: action=%s", action)
        await docker_update.execute_restart(action)
    except Exception:
        logger.exception(
            "scheduled Docker maintenance failed; restarting current image"
        )
        try:
            _message, action = await docker_update.prepare_restart_only()
            await docker_update.execute_restart(action)
        except Exception:
            logger.exception(
                "scheduled Docker restart failed; restarting bot process"
            )
            await fallback_restart()
