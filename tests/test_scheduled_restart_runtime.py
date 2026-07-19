from ironsbot.config.models.operations import RestartConfig
from ironsbot.plugins.operations import restart as scheduled_restart_runtime


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_register_restart_job_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()

    async def restart_process() -> None:
        return

    config = RestartConfig.model_validate(
        {
            "enabled": True,
            "times": ["04:30"],
            "grace_seconds": 0,
        }
    )

    scheduled_restart_runtime.register_restart_jobs(
        scheduler,
        restart_times=tuple(config.parsed_restart_times),
        grace_seconds=config.grace_seconds,
        restart_process=restart_process,
    )

    assert scheduler.jobs == [
        {
            "func": scheduled_restart_runtime._scheduled_restart,
            "trigger": "cron",
            "id": "scheduled_bot_restart:04:30",
            "replace_existing": True,
            "args": ["04:30", 0.0, restart_process],
            "hour": 4,
            "minute": 30,
            "second": 0,
            "timezone": scheduled_restart_runtime.LOCAL_TZ,
        }
    ]
