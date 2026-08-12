# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ironsbot.core.time import scheduled_clock_time
from ironsbot.services.operations.scheduler import JobRegistry

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService


def register_reconnect_jobs(
    scheduler: Any,
    service: HeadlessService,
) -> None:
    registry = JobRegistry(scheduler, prefix="headless_reconnect_check:")
    for scheduled_time in service.reconnect_times:
        clock_time = scheduled_clock_time(
            scheduled_time,
            error_message=(
                "operations.headless_notice.reconnect_check_times must contain "
                "daily HH:MM:SS times"
            ),
        )
        registry.add_daily(
            service.reconnect,
            job_id=str(clock_time),
            args=[scheduled_time],
            clock_time=clock_time,
        )
