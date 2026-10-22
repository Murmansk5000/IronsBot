from __future__ import annotations

import subprocess
import sys


def test_lifecycle_executes_resources_and_drains_tasks_without_nonebot() -> None:
    script = """
import asyncio
import importlib.abc
import sys

class RejectNoneBot(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'nonebot' or fullname.startswith('nonebot.'):
            raise AssertionError('framework imported by public lifecycle: ' + fullname)

sys.meta_path.insert(0, RejectNoneBot())
from ironsbot.app.lifecycle import ApplicationLifecycle, TaskOwner
from ironsbot.core.plugin_install import PluginContribution, PluginHooks

async def run():
    calls = []
    owner = TaskOwner()

    async def background():
        try:
            await asyncio.Event().wait()
        finally:
            calls.append('task_stop')

    async def service_start():
        calls.append('service_start')
        owner.create(background(), name='independent-lifecycle')
        await asyncio.sleep(0)

    class Scheduler:
        def start(self):
            calls.append('scheduler_start')
        async def shutdown(self):
            calls.append('scheduler_stop')

    contribution = PluginContribution(
        id='test',
        hooks=PluginHooks(
            startup=(('service', service_start),),
            shutdown=(('service', lambda: calls.append('service_stop')),),
        ),
    )
    lifecycle = ApplicationLifecycle.from_contributions(
        (contribution,), task_owner=owner, scheduler=Scheduler(),
        resource_startup_hooks=(('resource', lambda: calls.append('resource_start')),),
        resource_shutdown_hooks=(('resource', lambda: calls.append('resource_stop')),),
    )
    await lifecycle.startup()
    await lifecycle.shutdown()
    assert calls == [
        'resource_start', 'service_start', 'scheduler_start',
        'scheduler_stop', 'service_stop', 'task_stop', 'resource_stop',
    ], calls
    assert not owner.tasks
    assert not any(
        name == 'nonebot' or name.startswith('nonebot.') for name in sys.modules
    )

asyncio.run(run())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
