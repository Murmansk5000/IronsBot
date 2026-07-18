# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.integrations.scheduler.jobs import JobRegistry

from . import scan_team_resource_subscriptions

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.team_resource_subscriptions import TeamResourceService

TEAM_RESOURCE_JOB_PREFIX = "team_resource_scan_"


def register_team_resource_jobs(
    scheduler: Any,
    headless: HeadlessService,
    service: TeamResourceService,
) -> None:
    config = service.config
    if not config.enabled:
        return

    async def scan() -> None:
        await scan_team_resource_subscriptions(headless, service)

    registry = JobRegistry(scheduler, prefix=TEAM_RESOURCE_JOB_PREFIX)
    for time_text in config.times:
        hour_text, minute_text = time_text.split(":", maxsplit=1)
        registry.add(
            scan,
            "cron",
            hour=int(hour_text),
            minute=int(minute_text),
            job_id=time_text.replace(":", ""),
        )


__all__ = ["register_team_resource_jobs"]
