# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from ironsbot.shared.scheduler import add_or_replace_job, remove_jobs_by_prefix

from .planning import group_by_send_time

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .models import ActivityReminder

STARTUP_SCAN_JOB_ID = "activity_reminder_startup_scan"
DAILY_SCAN_JOB_ID = "activity_reminder_daily_scan"
REMINDER_JOB_ID_PREFIX = "activity_reminder_"
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

    add_or_replace_job(
        scheduler,
        scan_func,
        "date",
        job_id=STARTUP_SCAN_JOB_ID,
        next_run_time=now + STARTUP_SCAN_DELAY,
        misfire_grace_time=STARTUP_SCAN_MISFIRE_GRACE_SECONDS,
    )
    add_or_replace_job(
        scheduler,
        scan_func,
        "cron",
        job_id=DAILY_SCAN_JOB_ID,
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
        add_or_replace_job(
            scheduler,
            send_func,
            "date",
            kwargs={
                "lead_hours": lead_hours,
                "reminders": lead_reminders,
            },
            job_id=reminder_job_id(lead_hours, send_time),
            run_date=send_time,
            misfire_grace_time=grace_minutes * SECONDS_PER_MINUTE,
        )
        scheduled_count += len(lead_reminders)
    return scheduled_count


def clear_reminder_jobs(scheduler: Any) -> None:
    remove_jobs_by_prefix(
        scheduler,
        REMINDER_JOB_ID_PREFIX,
        exclude={STARTUP_SCAN_JOB_ID, DAILY_SCAN_JOB_ID},
    )
