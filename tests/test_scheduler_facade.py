from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.integrations.scheduler.facade import (
    SchedulerFacade,
    SchedulerStateError,
)

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


@dataclass(frozen=True, slots=True)
class FakeJob:
    id: str


class FakeScheduler:
    def __init__(self) -> None:
        self.running = False
        self.jobs: list[FakeJob] = []
        self.start_calls = 0
        self.shutdown_calls = 0

    def start(self) -> None:
        self.running = True
        self.start_calls += 1

    def shutdown(self) -> None:
        self.running = False
        self.shutdown_calls += 1

    def add_job(self, _func: object, _trigger: str, **kwargs: Any) -> FakeJob:
        job = FakeJob(str(kwargs["id"]))
        self.jobs.append(job)
        return job

    def get_jobs(self) -> list[FakeJob]:
        return list(self.jobs)

    def remove_job(self, job_id: str) -> None:
        self.jobs = [job for job in self.jobs if job.id != job_id]


def test_scheduler_facade_requires_bound_backend() -> None:
    facade = SchedulerFacade()

    with pytest.raises(SchedulerStateError):
        facade.start()


def test_scheduler_facade_owns_backend_lifecycle_and_jobs() -> None:
    backend = FakeScheduler()
    facade = SchedulerFacade()
    facade.bind(cast("AsyncIOScheduler", backend))

    facade.start()
    facade.start()
    facade.add_job(object(), "interval", id="job")

    assert backend.start_calls == 1
    assert [job.id for job in facade.get_jobs()] == ["job"]

    facade.remove_job("job")
    facade.shutdown()
    facade.shutdown()

    assert facade.get_jobs() == []
    assert backend.shutdown_calls == 1
