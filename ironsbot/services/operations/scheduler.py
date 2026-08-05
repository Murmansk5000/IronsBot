# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence

_T = TypeVar("_T")


class ScheduledJob(Protocol):
    id: str


class Scheduler(Protocol):
    def add_job(
        self,
        func: Any,
        trigger: str,
        **kwargs: Any,
    ) -> ScheduledJob: ...

    def get_jobs(self) -> Sequence[ScheduledJob]: ...

    def remove_job(self, job_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class JobRegistry:
    scheduler: Scheduler
    prefix: str = ""

    def job_id(self, suffix: str) -> str:
        return f"{self.prefix}{suffix}" if self.prefix else suffix

    def add(
        self,
        func: Any,
        trigger: str,
        *,
        job_id: str,
        replace_existing: bool = True,
        **kwargs: Any,
    ) -> Any:
        return self.scheduler.add_job(
            func,
            trigger,
            id=self.job_id(job_id),
            replace_existing=replace_existing,
            **kwargs,
        )

    def remove_by_prefix(
        self,
        prefix: str = "",
        *,
        exclude: Collection[str] = (),
    ) -> int:
        scoped_prefix = self.job_id(prefix)
        scoped_exclude = {self.job_id(job_id) for job_id in exclude}
        removed = 0
        for job in self.scheduler.get_jobs():
            job_id = str(job.id)
            if job_id.startswith(scoped_prefix) and job_id not in scoped_exclude:
                self.scheduler.remove_job(job_id)
                removed += 1
        return removed

    def replace_all(
        self,
        register: Callable[[JobRegistry], _T],
        *,
        exclude: Collection[str] = (),
    ) -> _T:
        self.remove_by_prefix(exclude=exclude)
        return register(self)
