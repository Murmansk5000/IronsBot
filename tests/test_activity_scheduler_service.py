from datetime import datetime
from zoneinfo import ZoneInfo

from ironsbot.services.activity.models import ActivityReminder
from ironsbot.services.activity.scheduler import (
    DAILY_SCAN_JOB_ID,
    STARTUP_SCAN_DELAY,
    STARTUP_SCAN_JOB_ID,
    register_scan_jobs,
    reminder_job_id,
    schedule_reminder_jobs,
)

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
EXPECTED_SCHEDULED_COUNT = 2
EXPECTED_MISFIRE_GRACE_SECONDS = 900


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def dt(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ)


def _scan() -> None:
    return None


def _send() -> None:
    return None


def _reminder(activity_id: int, send_time: datetime) -> ActivityReminder:
    return ActivityReminder(
        activity_id=activity_id,
        name=f"活动 {activity_id}",
        end_time=dt(2026, 6, 12, 10),
        lead_hours=1,
        send_time=send_time,
    )


def test_register_scan_jobs_installs_startup_and_daily_jobs() -> None:
    scheduler = FakeScheduler()
    now = dt(2026, 6, 12, 8)

    register_scan_jobs(scheduler, _scan, enabled=True, now=now)

    assert [job["id"] for job in scheduler.jobs] == [
        STARTUP_SCAN_JOB_ID,
        DAILY_SCAN_JOB_ID,
    ]
    assert scheduler.jobs[0]["next_run_time"] == now + STARTUP_SCAN_DELAY


def test_register_scan_jobs_skips_when_disabled() -> None:
    scheduler = FakeScheduler()

    register_scan_jobs(scheduler, _scan, enabled=False, now=dt(2026, 6, 12, 8))

    assert scheduler.jobs == []


def test_schedule_reminder_jobs_groups_by_send_time() -> None:
    scheduler = FakeScheduler()
    send_time = dt(2026, 6, 12, 9)
    reminders = [_reminder(1, send_time), _reminder(2, send_time)]

    scheduled_count = schedule_reminder_jobs(
        scheduler,
        _send,
        reminders,
        grace_minutes=15,
    )

    assert scheduled_count == EXPECTED_SCHEDULED_COUNT
    assert len(scheduler.jobs) == 1
    assert scheduler.jobs[0]["id"] == reminder_job_id(1, send_time)
    assert scheduler.jobs[0]["misfire_grace_time"] == EXPECTED_MISFIRE_GRACE_SECONDS
