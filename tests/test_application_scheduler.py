from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.integrations.scheduler.facade import SchedulerFacade


def test_application_scheduler_runs_without_nonebot_or_shared_global_backend() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import asyncio, sys
sys.modules['nonebot'] = None
sys.modules['nonebot_plugin_apscheduler'] = None
from ironsbot.integrations.scheduler.facade import SchedulerFacade

async def main():
    first = SchedulerFacade(timezone='Asia/Shanghai', spawn=asyncio.create_task)
    second = SchedulerFacade(timezone='Asia/Shanghai', spawn=asyncio.create_task)
    fired = asyncio.Event()
    async def work():
        fired.set()
    first.add_job(work, 'date', id='same')
    second.add_job(work, 'date', id='same')
    assert len(first.get_jobs()) == len(second.get_jobs()) == 1
    first.start()
    try:
        await asyncio.wait_for(fired.wait(), timeout=3)
        assert len(second.get_jobs()) == 1
    finally:
        await first.shutdown()
        await second.shutdown()
asyncio.run(main())
""",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_application_owns_scheduler_start_and_shutdown_order() -> None:
    calls: list[str] = []
    owner = TaskOwner()
    scheduler = SchedulerFacade(timezone="Asia/Shanghai", spawn=owner.create_draining)
    entered = asyncio.Event()

    async def work() -> None:
        calls.append("job_start")
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            calls.append("job_stop")

    async def register() -> None:
        calls.append("register")
        scheduler.add_job(work, "date", id="work")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not entered.is_set()
        calls.append("registered")

    async def background() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            calls.append("task_stop")

    lifecycle = ApplicationLifecycle(
        task_owner=owner,
        scheduler=scheduler,
        resource_startup_hooks=(("resource", lambda: calls.append("resource_start")),),
        startup_hooks=(("registration", register),),
        shutdown_hooks=(("service", lambda: calls.append("service_stop")),),
        resource_shutdown_hooks=(("resource", lambda: calls.append("resource_stop")),),
    )
    try:
        await lifecycle.startup()
        await asyncio.wait_for(entered.wait(), timeout=3)
        owner.create(background(), name="background")
        await asyncio.sleep(0)
        await lifecycle.shutdown()
        assert calls == [
            "resource_start",
            "register",
            "registered",
            "job_start",
            "job_stop",
            "service_stop",
            "task_stop",
            "resource_stop",
        ]
    finally:
        await lifecycle.shutdown()
