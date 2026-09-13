from typing import Any
from zoneinfo import ZoneInfo

from ironsbot.config.models.operations import RestartConfig
from ironsbot.services.operations import scheduled_restart as scheduled_restart_runtime


class FakeJob:
    id = "fake"


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: Any, trigger: str, **kwargs: Any) -> FakeJob:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})
        return FakeJob()

    def get_jobs(self) -> list[FakeJob]:
        return []

    def remove_job(self, job_id: str) -> None:
        del job_id


def test_register_restart_job_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()

    async def restart_process() -> None:
        return

    config = RestartConfig.model_validate(
        {
            "enabled": True,
            "times": ["04:30:17"],
            "grace_seconds": 0,
        }
    )

    service = scheduled_restart_runtime.ScheduledRestartService(
        restart_times=tuple(config.parsed_restart_times),
        grace_seconds=config.grace_seconds,
        restart_process=restart_process,
    )
    service.register_jobs(scheduler)

    assert scheduler.jobs == [
        {
            "func": scheduled_restart_runtime._scheduled_restart,
            "trigger": "cron",
            "id": "scheduled_bot_restart:04:30:17",
            "replace_existing": True,
            "args": ["04:30:17", 0.0, restart_process],
            "hour": 4,
            "minute": 30,
            "second": 17,
            "timezone": ZoneInfo("Asia/Shanghai"),
        }
    ]
