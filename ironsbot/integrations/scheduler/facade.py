# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apscheduler.job import Job
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


class SchedulerStateError(RuntimeError):
    pass


@dataclass(slots=True)
class SchedulerFacade:
    _backend: AsyncIOScheduler | None = field(default=None, init=False, repr=False)

    def bind(self, backend: AsyncIOScheduler) -> None:
        if self._backend is not None and self._backend is not backend:
            raise SchedulerStateError
        self._backend = backend

    def start(self) -> None:
        backend = self._require_backend()
        if not backend.running:
            backend.start()

    def shutdown(self) -> None:
        backend = self._require_backend()
        if backend.running:
            backend.shutdown()

    def add_job(self, *args: Any, **kwargs: Any) -> Job:
        return self._require_backend().add_job(*args, **kwargs)

    def get_jobs(self) -> list[Job]:
        return self._require_backend().get_jobs()

    def remove_job(self, job_id: str) -> None:
        self._require_backend().remove_job(job_id)

    def _require_backend(self) -> AsyncIOScheduler:
        if self._backend is None:
            raise SchedulerStateError
        return self._backend
