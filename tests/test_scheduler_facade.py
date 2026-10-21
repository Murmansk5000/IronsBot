from __future__ import annotations

import asyncio
import threading

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.scheduler.facade import SchedulerFacade, SchedulerStateError


@pytest.mark.asyncio
async def test_scheduler_owns_backend_lifecycle_and_jobs() -> None:
    facade = SchedulerFacade(timezone="Asia/Shanghai", spawn=asyncio.create_task)

    async def work() -> None:
        pass

    facade.add_job(work, "interval", hours=1, id="job")
    assert [job.id for job in facade.get_jobs()] == ["job"]
    facade.start()
    facade.start()
    try:
        facade.remove_job("job")
        assert facade.get_jobs() == []
        await facade.shutdown()
        await facade.shutdown()
        with pytest.raises(SchedulerStateError):
            facade.add_job(work, "date", id="late")
        facade.start()
        facade.add_job(work, "interval", hours=1, id="restarted")
        assert [job.id for job in facade.get_jobs()] == ["restarted"]
    finally:
        await facade.shutdown()


@pytest.mark.asyncio
async def test_external_cancel_and_late_callback_suppression() -> None:
    facade = SchedulerFacade(timezone="Asia/Shanghai", spawn=asyncio.create_task)
    entered = asyncio.Event()

    async def work() -> None:
        entered.set()
        await asyncio.Event().wait()

    wrapped = facade.add_job(work, "date", id="job").func
    running = asyncio.create_task(wrapped())
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        entered.clear()
        await facade.shutdown()
        assert await wrapped() is None
        assert not entered.is_set()
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        await facade.shutdown()


@pytest.mark.asyncio
async def test_scheduler_shutdown_waits_for_running_async_job_cleanup() -> None:
    facade = SchedulerFacade(timezone="Asia/Shanghai", spawn=asyncio.create_task)
    entered = asyncio.Event()
    cancelling = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def work() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelling.set()
            await release.wait()
            finished.set()

    facade.add_job(work, "date", id="running")
    facade.start()
    stopping: asyncio.Task[None] | None = None
    another: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        stopping = asyncio.create_task(facade.shutdown())
        await asyncio.wait_for(cancelling.wait(), timeout=3)
        assert not stopping.done()
        assert not finished.is_set()
        with pytest.raises(SchedulerStateError):
            facade.start()
        with pytest.raises(SchedulerStateError):
            facade.add_job(work, "date", id="late")
        another = asyncio.create_task(facade.shutdown())
        await asyncio.sleep(0)
        assert not another.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(stopping, another), timeout=3)
        assert finished.is_set()
        assert facade.get_jobs() == []
    finally:
        release.set()
        await facade.shutdown()
        await asyncio.gather(
            *[task for task in (stopping, another) if task is not None],
            return_exceptions=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword", [False, True])
async def test_sync_jobs_are_off_loop_and_drained_before_shutdown(
    *, keyword: bool
) -> None:
    owner = TaskOwner()
    facade = SchedulerFacade(timezone="Asia/Shanghai", spawn=owner.create_draining)
    entered = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()
    loop = asyncio.get_running_loop()
    event_thread = threading.get_ident()

    def work() -> None:
        assert threading.get_ident() != event_thread
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=5)
        finished.set()

    if keyword:
        facade.add_job(func=work, trigger="date", id="sync")
    else:
        facade.add_job(work, "date", id="sync")
    facade.start()
    stopping: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        stopping = asyncio.create_task(facade.shutdown())
        await asyncio.sleep(0)
        await asyncio.wait_for(asyncio.sleep(0), timeout=1)
        assert not stopping.done()
        assert not finished.is_set()
        release.set()
        await asyncio.wait_for(stopping, timeout=3)
        assert finished.is_set()
        assert not owner.tasks
    finally:
        release.set()
        await facade.shutdown()
        if stopping is not None:
            await asyncio.gather(stopping, return_exceptions=True)
