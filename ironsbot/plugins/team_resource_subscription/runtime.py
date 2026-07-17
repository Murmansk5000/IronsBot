# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from nonebot import get_driver, require

from ironsbot.shared.runtime.jobs import JobRegistry

from . import scan_team_resource_subscriptions
from .config import get_team_resource_config

_team_resource_runtime_state = {"registered": False}
TEAM_RESOURCE_JOB_PREFIX = "team_resource_scan_"


async def _scan_team_resources() -> None:
    await scan_team_resource_subscriptions()


def _register_team_resource_jobs(scheduler: Any) -> None:
    config = get_team_resource_config()
    if not config.enabled:
        return

    registry = JobRegistry(scheduler, prefix=TEAM_RESOURCE_JOB_PREFIX)
    for time_text in config.times:
        hour_text, minute_text = time_text.split(":", maxsplit=1)
        registry.add(
            _scan_team_resources,
            "cron",
            hour=int(hour_text),
            minute=int(minute_text),
            job_id=time_text.replace(":", ""),
        )


def _setup_team_resource_runtime(driver: Any, scheduler: Any) -> None:
    if _team_resource_runtime_state["registered"]:
        return

    @driver.on_startup
    async def _register_team_resource_jobs_on_startup() -> None:
        _register_team_resource_jobs(scheduler)

    _team_resource_runtime_state["registered"] = True


def setup_team_resource_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_team_resource_runtime(get_driver(), scheduler)


__all__ = ["setup_team_resource_runtime"]
