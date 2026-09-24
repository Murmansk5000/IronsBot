from typing import Any, cast
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

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


def test_restart_defaults_to_one_am() -> None:
    config = RestartConfig()
    assert config.parsed_restart_times == ["01:00:00"]

    scheduler = FakeScheduler()
    restart = AsyncMock()
    service = scheduled_restart_runtime.ScheduledRestartService(
        ("01:00:00",), 0, restart
    )
    service.register_jobs(scheduler)
    assert scheduler.jobs[0]["args"] == ["01:00:00", 0, restart]


@pytest.mark.asyncio
async def test_scheduled_update_uses_existing_docker_maintenance() -> None:
    docker_update = cast("Any", AsyncMock())
    docker_update.prepare_update_and_restart.return_value = ("checked", "none")
    restart = AsyncMock()

    await scheduled_restart_runtime.update_image_and_restart(
        docker_update, restart
    )

    docker_update.execute_restart.assert_awaited_once_with("none")
    restart.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_update_falls_back_when_check_fails() -> None:
    docker_update = cast("Any", AsyncMock())
    docker_update.prepare_update_and_restart.side_effect = OSError("unavailable")
    docker_update.prepare_restart_only.return_value = ("restart", "docker")
    restart = AsyncMock()

    await scheduled_restart_runtime.update_image_and_restart(
        docker_update, restart
    )

    docker_update.execute_restart.assert_awaited_once_with("docker")
    restart.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_update_falls_back_to_process_when_docker_fails() -> None:
    docker_update = cast("Any", AsyncMock())
    docker_update.prepare_update_and_restart.side_effect = OSError("unavailable")
    docker_update.prepare_restart_only.side_effect = OSError("socket unavailable")
    restart = AsyncMock()

    await scheduled_restart_runtime.update_image_and_restart(
        docker_update, restart
    )

    restart.assert_awaited_once()
