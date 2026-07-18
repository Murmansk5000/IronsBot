import asyncio
from functools import partial

from ironsbot.plugins.bilibili import runtime as bili_runtime
from tests.helpers.runtime import build_test_runtime


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_register_bili_auto_check_job_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()
    admin_notices = build_test_runtime().admin_notices

    asyncio.run(
        bili_runtime.register_bili_auto_check_job(scheduler, admin_notices)
    )

    job = scheduler.jobs[0]
    func = job.pop("func")
    assert isinstance(func, partial)
    assert func.func is bili_runtime.run_check_logic
    assert func.args == (admin_notices,)
    assert job == {
        "trigger": "interval",
        "id": "bilibili_monitor_auto_check",
        "replace_existing": True,
        "minutes": 1,
    }
