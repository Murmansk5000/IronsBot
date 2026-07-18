import asyncio

from ironsbot.plugins.bilibili import runtime as bili_runtime


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_register_bili_auto_check_job_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()

    asyncio.run(bili_runtime.register_bili_auto_check_job(scheduler))

    assert scheduler.jobs == [
        {
            "func": bili_runtime.run_check_logic,
            "trigger": "interval",
            "id": "bilibili_monitor_auto_check",
            "replace_existing": True,
            "minutes": 1,
        }
    ]
