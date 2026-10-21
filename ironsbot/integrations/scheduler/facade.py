# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from functools import partial, wraps
from typing import TYPE_CHECKING, Any

from apscheduler.events import EVENT_SCHEDULER_SHUTDOWN
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ironsbot.core.tasks import run_owned_blocking

if TYPE_CHECKING:
    from apscheduler.events import SchedulerEvent
    from apscheduler.job import Job

    from ironsbot.core.tasks import TaskSpawner

logger = logging.getLogger(__name__)


class SchedulerStateError(RuntimeError):
    pass


@dataclass(slots=True)
class SchedulerFacade:
    timezone: str | None = None
    spawn: TaskSpawner = field(kw_only=True, repr=False, compare=False)
    _backend: AsyncIOScheduler = field(init=False, repr=False)
    _stopping: bool = field(default=False, init=False, repr=False)
    _shutdown_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )
    _running: set[asyncio.Task[Any]] = field(
        default_factory=set, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self._backend = AsyncIOScheduler(timezone=self.timezone)

    def start(self) -> None:
        if self._shutdown_lock.locked():
            message = "Scheduler is shutting down"
            raise SchedulerStateError(message)
        if not self._backend.running:
            self._stopping = False
            self._backend.start()

    async def shutdown(self) -> None:
        async with self._shutdown_lock:
            self._stopping = True
            if not self._backend.running:
                self._backend.remove_all_jobs()
                return
            stopped = asyncio.get_running_loop().create_future()

            def on_stopped(_event: SchedulerEvent) -> None:
                if not stopped.done():
                    stopped.set_result(None)

            self._backend.add_listener(on_stopped, EVENT_SCHEDULER_SHUTDOWN)
            try:
                self._backend.shutdown(wait=False)
                await stopped
                if self._running:
                    await asyncio.gather(*tuple(self._running), return_exceptions=True)
            finally:
                self._backend.remove_listener(on_stopped)

    def add_job(self, func: Any, *args: Any, **kwargs: Any) -> Job:
        if self._stopping:
            message = "Scheduler is stopping"
            raise SchedulerStateError(message)
        return self._backend.add_job(
            self._shutdown_safe(func, str(kwargs.get("id", "unknown"))),
            *args,
            **kwargs,
        )

    def get_jobs(self) -> list[Job]:
        return self._backend.get_jobs()

    def remove_job(self, job_id: str) -> None:
        self._backend.remove_job(job_id)

    def _shutdown_safe(self, func: Any, job_id: str) -> Any:
        @wraps(func)
        async def run(*args: Any, **kwargs: Any) -> Any:
            if self._stopping:
                return None
            task = asyncio.current_task()
            if task is not None:
                self._running.add(task)
            try:
                result = (
                    func(*args, **kwargs)
                    if inspect.iscoroutinefunction(func)
                    else await run_owned_blocking(
                        partial(func, *args, **kwargs),
                        spawn=self.spawn,
                        name="scheduled_job",
                    )
                )
                return await result if inspect.isawaitable(result) else result
            except asyncio.CancelledError:
                if not self._stopping:
                    raise
                logger.debug("scheduled job cancelled during shutdown: job=%s", job_id)
                return None
            finally:
                if task is not None:
                    self._running.discard(task)

        return run
