# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from functools import wraps
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apscheduler.job import Job
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)


class SchedulerStateError(RuntimeError):
    pass


@dataclass(slots=True)
class SchedulerFacade:
    timezone: str | None = None
    _backend: AsyncIOScheduler | None = field(default=None, init=False, repr=False)
    _stopping: bool = field(default=False, init=False, repr=False)

    def bind(self, backend: AsyncIOScheduler) -> None:
        if self._backend is not None and self._backend is not backend:
            raise SchedulerStateError
        self._backend = backend

    def start(self) -> None:
        backend = self._require_backend()
        if not backend.running:
            self._stopping = False
            backend.start()

    def shutdown(self) -> None:
        backend = self._require_backend()
        if backend.running:
            self._stopping = True
            backend.shutdown()

    def add_job(self, *args: Any, **kwargs: Any) -> Job:
        if not args:
            return self._require_backend().add_job(*args, **kwargs)
        func, *remaining = args
        return self._require_backend().add_job(
            self._shutdown_safe(func, str(kwargs.get("id", "unknown"))),
            *remaining,
            **kwargs,
        )

    def get_jobs(self) -> list[Job]:
        return self._require_backend().get_jobs()

    def remove_job(self, job_id: str) -> None:
        self._require_backend().remove_job(job_id)

    def _require_backend(self) -> AsyncIOScheduler:
        if self._backend is None:
            raise SchedulerStateError
        return self._backend

    def _shutdown_safe(self, func: Any, job_id: str) -> Any:
        if not inspect.iscoroutinefunction(func):
            return func

        @wraps(func)
        async def run(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except asyncio.CancelledError:
                if not self._stopping:
                    raise
                logger.debug("scheduled job cancelled during shutdown: job=%s", job_id)
                return None

        return run
