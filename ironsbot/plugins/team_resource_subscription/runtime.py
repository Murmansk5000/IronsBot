# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from ironsbot.integrations.scheduler.jobs import JobRegistry

from . import scan_team_resource_subscriptions
from .config import get_team_resource_config

TEAM_RESOURCE_JOB_PREFIX = "team_resource_scan_"


async def _scan_team_resources() -> None:
    await scan_team_resource_subscriptions()


def register_team_resource_jobs(scheduler: Any) -> None:
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


__all__ = ["register_team_resource_jobs"]
