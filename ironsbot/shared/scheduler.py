# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Container, Iterable
from typing import Any


def remove_jobs_by_prefix(
    scheduler: Any,
    prefix: str,
    *,
    exclude: Container[str] = (),
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


__all__ = ["remove_jobs_by_prefix"]

