from dataclasses import dataclass

from ironsbot.shared.scheduler import (
    JobRegistry,
    add_or_replace_job,
    remove_jobs_by_prefix,
)


@dataclass(frozen=True)
class FakeJob:
    id: str


class FakeScheduler:
    def __init__(self, job_ids: list[str] | None = None) -> None:
        job_ids = job_ids or []
        self.jobs = [FakeJob(id=job_id) for job_id in job_ids]
        self.added_jobs: list[dict[str, object]] = []
        self.removed: list[str] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> object:
        job = {"func": func, "trigger": trigger, **kwargs}
        self.added_jobs.append(job)
        return job

    def get_jobs(self) -> list[FakeJob]:
        return self.jobs

    def remove_job(self, job_id: str) -> None:
        self.removed.append(job_id)


def test_remove_jobs_by_prefix_skips_excluded_jobs() -> None:
    scheduler = FakeScheduler(
        [
            "activity_reminder_startup_scan",
            "activity_reminder_1h_123",
            "message_schedule_group_1",
        ]
    )

    removed = remove_jobs_by_prefix(
        scheduler,
        "activity_reminder_",
        exclude={"activity_reminder_startup_scan"},
    )

    assert removed == 1
    assert scheduler.removed == ["activity_reminder_1h_123"]


def test_remove_jobs_by_prefix_tolerates_incomplete_scheduler() -> None:
    assert remove_jobs_by_prefix(object(), "message_schedule_") == 0


def test_add_or_replace_job_sets_standard_job_fields() -> None:
    scheduler = FakeScheduler()

    job = add_or_replace_job(
        scheduler,
        "task",
        "interval",
        job_id="unit_job",
        minutes=15,
        args=["unit"],
    )

    assert job == {
        "func": "task",
        "trigger": "interval",
        "id": "unit_job",
        "replace_existing": True,
        "minutes": 15,
        "args": ["unit"],
    }
    assert scheduler.added_jobs == [job]


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

    assert job["id"] == "activity_reminder_startup_scan"
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

    def register_jobs(active_registry: JobRegistry) -> object:
        return active_registry.add("task", "cron", job_id="new", minute=0)

    job = registry.replace_all(register_jobs, exclude={"keep"})

    assert isinstance(job, dict)
    assert scheduler.removed == ["message_action_old"]
    assert job["id"] == "message_action_new"
    assert scheduler.added_jobs == [job]
