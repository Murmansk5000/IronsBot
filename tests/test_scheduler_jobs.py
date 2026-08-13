from dataclasses import dataclass
from datetime import datetime, timezone

from ironsbot.core.time import ScheduledClockTime
from ironsbot.services.operations.scheduler import (
    JobRegistry,
    wall_clock_interval_trigger,
)

FALLBACK_INTERVAL_MINUTES = 90


@dataclass
class FakeJob:
    id: str


class FakeScheduler:
    def __init__(self, job_ids: list[str] | None = None) -> None:
        job_ids = job_ids or []
        self.jobs = [FakeJob(id=job_id) for job_id in job_ids]
        self.added_jobs: list[dict[str, object]] = []
        self.removed: list[str] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> FakeJob:
        job = {"func": func, "trigger": trigger, **kwargs}
        self.added_jobs.append(job)
        return FakeJob(str(kwargs["id"]))

    def get_jobs(self) -> list[FakeJob]:
        return self.jobs

    def remove_job(self, job_id: str) -> None:
        self.removed.append(job_id)


class TimezoneFakeScheduler(FakeScheduler):
    timezone = "Asia/Shanghai"


def test_job_registry_scopes_job_ids_and_prefix_removal() -> None:
    scheduler = FakeScheduler(
        [
            "activity_reminder_startup_scan",
            "activity_reminder_1h_123",
            "message_schedule_group_1",
        ]
    )
    registry = JobRegistry(scheduler, prefix="activity_reminder_")

    job = registry.add(
        "task",
        "date",
        job_id="startup_scan",
        next_run_time="soon",
    )
    removed = registry.remove_by_prefix(exclude={"startup_scan"})

    assert job.id == "activity_reminder_startup_scan"
    assert removed == 1
    assert scheduler.removed == ["activity_reminder_1h_123"]


def test_job_registry_replace_all_clears_prefix_before_registering() -> None:
    scheduler = FakeScheduler(
        [
            "message_action_old",
            "message_action_keep",
            "activity_reminder_1h_123",
        ]
    )
    registry = JobRegistry(scheduler, prefix="message_action_")

    def register_jobs(active_registry: JobRegistry) -> FakeJob:
        return active_registry.add("task", "cron", job_id="new", minute=0)

    job = registry.replace_all(register_jobs, exclude={"keep"})

    assert scheduler.removed == ["message_action_old"]
    assert job.id == "message_action_new"
    assert scheduler.added_jobs == [
        {
            "func": "task",
            "trigger": "cron",
            "id": "message_action_new",
            "replace_existing": True,
            "minute": 0,
        }
    ]


def test_wall_clock_interval_uses_exact_minute_boundaries() -> None:
    trigger, kwargs = wall_clock_interval_trigger(15)

    assert trigger == "cron"
    assert kwargs == {"minute": "*/15", "second": 0}


def test_wall_clock_interval_supports_a_second_phase() -> None:
    trigger, kwargs = wall_clock_interval_trigger(
        15,
        offset_minutes=4,
        offset_seconds=5,
    )

    assert trigger == "cron"
    assert kwargs == {"minute": "4/15", "second": 5}


def test_job_registry_registers_daily_time_with_seconds() -> None:
    scheduler = FakeScheduler()
    registry = JobRegistry(scheduler)

    registry.add_daily(
        "task",
        clock_time=ScheduledClockTime.parse(
            "04:30:05",
            error_message="invalid time",
        ),
        job_id="daily",
    )

    assert scheduler.added_jobs == [
        {
            "func": "task",
            "trigger": "cron",
            "id": "daily",
            "replace_existing": True,
            "hour": 4,
            "minute": 30,
            "second": 5,
        }
    ]


def test_job_registry_applies_the_configured_scheduler_timezone() -> None:
    scheduler = TimezoneFakeScheduler()
    registry = JobRegistry(scheduler)

    registry.add_daily(
        "task",
        clock_time=ScheduledClockTime(4, 30, 5),
        job_id="daily",
    )

    assert scheduler.added_jobs[0]["timezone"] == "Asia/Shanghai"


def test_wall_clock_interval_fallback_starts_on_next_aligned_slot() -> None:
    trigger, kwargs = wall_clock_interval_trigger(
        FALLBACK_INTERVAL_MINUTES,
        now=datetime(2026, 8, 12, 14, 23, 41, tzinfo=timezone.utc),
    )

    assert trigger == "interval"
    assert kwargs["minutes"] == FALLBACK_INTERVAL_MINUTES
    start_date = kwargs["start_date"]
    assert isinstance(start_date, datetime)
    assert start_date.minute in {0, 30}
    assert start_date.second == 0


def test_wall_clock_interval_fallback_uses_the_scheduler_timezone() -> None:
    trigger, kwargs = wall_clock_interval_trigger(
        FALLBACK_INTERVAL_MINUTES,
        offset_minutes=30,
        offset_seconds=5,
        schedule_timezone="Asia/Shanghai",
        now=datetime(2026, 8, 12, 14, 23, 41, tzinfo=timezone.utc),
    )

    assert trigger == "interval"
    assert kwargs["start_date"] == datetime(
        2026,
        8,
        12,
        23,
        0,
        5,
        tzinfo=kwargs["start_date"].tzinfo,
    )
