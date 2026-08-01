# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.core.time import daily_time_parts
from ironsbot.services.operations.scheduler import JobRegistry

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.headless_pool import HeadlessPool


def register_reconnect_jobs(
    scheduler: Any,
    service: HeadlessService | HeadlessPool,
) -> None:
    registry = JobRegistry(scheduler, prefix="headless_reconnect_check:")
    for scheduled_time in service.reconnect_times:
        hour, minute = daily_time_parts(scheduled_time)
        registry.add(
            service.reconnect,
            "cron",
            job_id=scheduled_time,
            args=[scheduled_time],
            hour=hour,
            minute=minute,
            second=0,
            timezone="Asia/Shanghai",
        )
