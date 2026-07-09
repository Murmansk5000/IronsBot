# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class JobRegistry:
    scheduler: Any
    prefix: str = ""

    def job_id(self, suffix: str) -> str:
        if not self.prefix:
            return suffix
        return f"{self.prefix}{suffix}"

    def add(
        self,
        func: Any,
        trigger: str,
        *,
        job_id: str,
        replace_existing: bool = True,
        **kwargs: Any,
    ) -> Any:
        return add_or_replace_job(
            self.scheduler,
            func,
            trigger,
            job_id=self.job_id(job_id),
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
        return remove_jobs_by_prefix(
            self.scheduler,
            scoped_prefix,
            exclude=scoped_exclude,
        )


def add_or_replace_job(
    scheduler: Any,
    func: Any,
    trigger: str,
    *,
    job_id: str,
    replace_existing: bool = True,
    **kwargs: Any,
) -> Any:
    return scheduler.add_job(
        func,
        trigger,
        id=job_id,
        replace_existing=replace_existing,
        **kwargs,
    )


def remove_jobs_by_prefix(
    scheduler: Any,
    prefix: str,
    *,
    exclude: Collection[str] = (),
) -> int:
    get_jobs = getattr(scheduler, "get_jobs", None)
    remove_job = getattr(scheduler, "remove_job", None)
    if not callable(get_jobs) or not callable(remove_job):
        return 0

    jobs = get_jobs()
    if not isinstance(jobs, Iterable):
        return 0

    removed = 0
    for job in list(jobs):
        job_id = str(getattr(job, "id", ""))
        if not job_id.startswith(prefix) or job_id in exclude:
            continue
        remove_job(job_id)
        removed += 1
    return removed


__all__ = ["JobRegistry", "add_or_replace_job", "remove_jobs_by_prefix"]
