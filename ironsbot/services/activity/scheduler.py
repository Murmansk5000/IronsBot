# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .planning import group_by_send_time

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .models import ActivityReminder

STARTUP_SCAN_JOB_ID = "activity_reminder_startup_scan"
DAILY_SCAN_JOB_ID = "activity_reminder_daily_scan"
STARTUP_SCAN_DELAY = timedelta(seconds=30)
STARTUP_SCAN_MISFIRE_GRACE_SECONDS = 300
DAILY_SCAN_MISFIRE_GRACE_SECONDS = 300
SECONDS_PER_MINUTE = 60


def reminder_job_id(lead_hours: int, send_time: datetime) -> str:
    return f"activity_reminder_{lead_hours}h_{int(send_time.timestamp())}"


def register_scan_jobs(
    scheduler: Any,
    scan_func: Callable[..., object],
    *,
    enabled: bool,
    now: datetime,
) -> None:
    if not enabled:
        return

    scheduler.add_job(
        scan_func,
        "date",
        id=STARTUP_SCAN_JOB_ID,
        replace_existing=True,
        next_run_time=now + STARTUP_SCAN_DELAY,
        misfire_grace_time=STARTUP_SCAN_MISFIRE_GRACE_SECONDS,
    )
    scheduler.add_job(
        scan_func,
        "cron",
        id=DAILY_SCAN_JOB_ID,
        replace_existing=True,
        hour=0,
        minute=0,
        second=0,
        misfire_grace_time=DAILY_SCAN_MISFIRE_GRACE_SECONDS,
    )


def schedule_reminder_jobs(
    scheduler: Any,
    send_func: Callable[..., object],
    reminders: Iterable[ActivityReminder],
    *,
    grace_minutes: int,
) -> int:
    scheduled_count = 0
    for (lead_hours, send_time), lead_reminders in group_by_send_time(
        reminders
    ).items():
        scheduler.add_job(
            send_func,
            "date",
            kwargs={
                "lead_hours": lead_hours,
                "reminders": lead_reminders,
            },
            id=reminder_job_id(lead_hours, send_time),
            replace_existing=True,
            run_date=send_time,
            misfire_grace_time=grace_minutes * SECONDS_PER_MINUTE,
        )
        scheduled_count += len(lead_reminders)
    return scheduled_count
