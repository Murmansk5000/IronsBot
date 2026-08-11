from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from ironsbot.services.bilibili.runtime import BilibiliMonitorService
from tests.helpers.bilibili import build_test_bilibili_service

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.bilibili import SeerDynamicCategory
    from ironsbot.services.operations.scheduler import Scheduler


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


async def _ignore_auth_invalid(_reason: str) -> None:
    return None


async def _ignore_push(
    _item: dict[str, object],
    _pub_ts: int,
    _author_mid: int,
    _targets: object,
    _categories: tuple[SeerDynamicCategory, ...] = (),
) -> None:
    return None


def test_bili_monitor_service_registers_standard_scheduler_job(
    tmp_path: Path,
) -> None:
    scheduler = FakeScheduler()
    service = build_test_bilibili_service(tmp_path)
    monitor = BilibiliMonitorService(
        service,
        _ignore_auth_invalid,
        _ignore_push,
    )

    asyncio.run(
        monitor.register_job(cast("Scheduler", scheduler))
    )

    job = scheduler.jobs[0]
    func = job.pop("func")
    assert func == monitor.check
    assert job == {
        "trigger": "interval",
        "id": "bilibili_monitor_auto_check",
        "replace_existing": True,
        "minutes": 1,
    }
