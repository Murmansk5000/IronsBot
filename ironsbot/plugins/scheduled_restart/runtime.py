# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import os
import signal
from typing import Any
from zoneinfo import ZoneInfo

from nonebot import get_driver, logger, require

from ironsbot.shared.config.time import daily_time_parts
from ironsbot.shared.runtime.jobs import JobRegistry

from .config import INVALID_RESTART_TIME_ERROR, get_restart_config

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
JOB_ID = "scheduled_bot_restart"
PARENT_EXIT_WAIT_SECONDS = 5.0

_scheduled_restart_runtime_state = {"registered": False}


def _target_pid() -> int:
    if not get_restart_config().signal_parent:
        return os.getpid()

    parent_pid = os.getppid()
    if parent_pid > 0:
        return parent_pid

    return os.getpid()


async def _scheduled_restart(scheduled_time: str) -> None:
    grace_seconds = get_restart_config().grace_seconds
    if grace_seconds > 0:
        logger.warning(
            "scheduled bot restart {} will signal process in {:.1f}s",
            scheduled_time,
            grace_seconds,
        )
        await asyncio.sleep(grace_seconds)

    current_pid = os.getpid()
    target_pid = _target_pid()
    logger.warning(
        "scheduled bot restart sending SIGTERM: "
        "time={}, current_pid={}, target_pid={}",
        scheduled_time,
        current_pid,
        target_pid,
    )
    os.kill(target_pid, signal.SIGTERM)

    if target_pid != current_pid:
        await asyncio.sleep(PARENT_EXIT_WAIT_SECONDS)
        logger.warning(
            "scheduled bot restart parent did not stop current worker yet; "
            f"sending SIGTERM to current_pid={current_pid}"
        )
        os.kill(current_pid, signal.SIGTERM)


def _register_restart_job(scheduler: Any) -> None:
    restart_config = get_restart_config()
    if not restart_config.enabled:
        logger.info("scheduled bot restart disabled")
        return

    restart_times = restart_config.parsed_restart_times
    registry = JobRegistry(scheduler, prefix=f"{JOB_ID}:")
    for scheduled_time in restart_times:
        hour, minute = daily_time_parts(
            scheduled_time,
            error_message=INVALID_RESTART_TIME_ERROR,
        )
        registry.add(
            _scheduled_restart,
            "cron",
            job_id=scheduled_time,
            args=[scheduled_time],
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


def _setup_scheduled_restart_runtime(driver: Any, scheduler: Any) -> None:
    if _scheduled_restart_runtime_state["registered"]:
        return

    @driver.on_startup
    async def register_restart_job() -> None:
        _register_restart_job(scheduler)

    _scheduled_restart_runtime_state["registered"] = True


def setup_scheduled_restart_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_scheduled_restart_runtime(get_driver(), scheduler)


__all__ = ["setup_scheduled_restart_runtime"]
