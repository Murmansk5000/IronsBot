from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from ironsbot.services.bilibili import monitor as monitor_module
from ironsbot.services.bilibili.monitor import run_monitor_check
from ironsbot.services.bilibili.runtime import BilibiliMonitorService
from tests.helpers.bilibili import build_test_bilibili_service

EXPECTED_CATCH_UP_CHECK_COUNT = 2

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

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


def test_bili_monitor_service_registers_wall_clock_job(
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

    assert len(scheduler.jobs) == 1
    job = scheduler.jobs[0]
    func = job.pop("func")
    assert func == monitor.check
    assert job == {
        "trigger": "cron",
        "id": "bilibili_monitor_auto_check",
        "replace_existing": True,
        "minute": "*",
        "second": 5,
    }


def test_running_monitor_coalesces_missed_tick_into_one_catch_up(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def fake_check_logic(*_args: object, **_kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()

    monkeypatch.setattr(monitor_module, "_do_check_logic", fake_check_logic)

    async def scenario() -> None:
        first = asyncio.create_task(
            run_monitor_check(
                service,
                on_auth_invalid=_ignore_auth_invalid,
                send_push=_ignore_push,
                force=True,
            )
        )
        await started.wait()
        assert not await run_monitor_check(
            service,
            on_auth_invalid=_ignore_auth_invalid,
            send_push=_ignore_push,
            force=True,
        )
        assert not await run_monitor_check(
            service,
            on_auth_invalid=_ignore_auth_invalid,
            send_push=_ignore_push,
            force=True,
        )
        release.set()
        assert await first

    asyncio.run(scenario())
    assert calls == EXPECTED_CATCH_UP_CHECK_COUNT
