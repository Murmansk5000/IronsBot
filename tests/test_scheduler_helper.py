from types import SimpleNamespace

from ironsbot.shared.scheduler import remove_jobs_by_prefix


class FakeScheduler:
    def __init__(self, job_ids: list[str]) -> None:
        self.jobs = [SimpleNamespace(id=job_id) for job_id in job_ids]
        self.removed: list[str] = []

    def get_jobs(self) -> list[SimpleNamespace]:
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

