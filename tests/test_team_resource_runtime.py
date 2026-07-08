import nonebot
from pytest import MonkeyPatch

from ironsbot.config.models.seer import TeamResourceConfig

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.team_resource_subscription import runtime


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_register_team_resource_jobs_uses_standard_scheduler_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        runtime,
        "get_team_resource_config",
        lambda: TeamResourceConfig(
            enabled=True,
            times=["22:30", "23:45"],
        ),
    )

    runtime._register_team_resource_jobs(scheduler)

    assert scheduler.jobs == [
        {
            "func": runtime._scan_team_resources_with_bot,
            "trigger": "cron",
            "id": "team_resource_scan_2230",
            "replace_existing": True,
            "hour": 22,
            "minute": 30,
        },
        {
            "func": runtime._scan_team_resources_with_bot,
            "trigger": "cron",
            "id": "team_resource_scan_2345",
            "replace_existing": True,
            "hour": 23,
            "minute": 45,
        },
    ]


def test_register_team_resource_jobs_skips_when_disabled(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        runtime,
        "get_team_resource_config",
        lambda: TeamResourceConfig(enabled=False, times=["23:00"]),
    )

    runtime._register_team_resource_jobs(scheduler)

    assert scheduler.jobs == []
