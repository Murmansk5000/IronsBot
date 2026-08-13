from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from ironsbot.core.bilibili import BiliBoostWindow, BiliPollingConfig
from ironsbot.services.bilibili import monitor as monitor_module
from ironsbot.services.bilibili.monitor import MonitorCheckResult, run_monitor_check
from ironsbot.services.bilibili.runtime import BilibiliMonitorService
from tests.helpers.bilibili import build_test_bilibili_service

BOOST_ATTEMPT_COUNT = 4

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

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
) -> None:
    return None


def test_bili_monitor_service_registers_second_precision_scheduler_job(
    tmp_path: Path,
) -> None:
    scheduler = FakeScheduler()
    service = build_test_bilibili_service(tmp_path)
    monitor = BilibiliMonitorService(
        service,
        _ignore_auth_invalid,
        _ignore_push,
    )

    asyncio.run(monitor.register_job(cast("Scheduler", scheduler)))

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


def test_bili_monitor_registers_extra_release_burst_jobs(tmp_path: Path) -> None:
    scheduler = FakeScheduler()
    service = build_test_bilibili_service(tmp_path)
    service.config = service.config.model_copy(
        update={
            "polling": BiliPollingConfig(
                boost_windows=[
                    BiliBoostWindow(
                        start="10:00:00",
                        end="11:00:00",
                        interval_minutes=60,
                        offset_seconds=[0, 5, 10, 15],
                    )
                ]
            )
        }
    )
    monitor = BilibiliMonitorService(service, _ignore_auth_invalid, _ignore_push)

    asyncio.run(monitor.register_job(cast("Scheduler", scheduler)))

    boost_job_times = [
        (job["hour"], job["minute"], job["second"]) for job in scheduler.jobs[1:]
    ]
    assert boost_job_times == [
        (10, 0, 0),
        (10, 0, 10),
        (10, 0, 15),
    ]


def test_new_dynamic_stops_the_rest_of_its_release_burst(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    service.config = service.config.model_copy(
        update={
            "polling": BiliPollingConfig(
                boost_windows=[
                    BiliBoostWindow(
                        start="10:00:00",
                        end="11:00:00",
                        interval_minutes=60,
                        offset_seconds=[0, 5, 10, 15],
                    )
                ]
            )
        }
    )
    calls = 0

    async def fake_check_logic(*_args: object, **_kwargs: object) -> MonitorCheckResult:
        nonlocal calls
        calls += 1
        return MonitorCheckResult(
            executed=True,
            valid_response=True,
            discovered_new=True,
        )

    monkeypatch.setattr(monitor_module, "_do_check_logic", fake_check_logic)

    async def scenario() -> None:
        first = await run_monitor_check(
            service,
            on_auth_invalid=_ignore_auth_invalid,
            send_push=_ignore_push,
            now=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        )
        second = await run_monitor_check(
            service,
            on_auth_invalid=_ignore_auth_invalid,
            send_push=_ignore_push,
            now=datetime(2026, 1, 1, 10, 0, 5, tzinfo=timezone.utc),
        )
        assert first.discovered_new
        assert not second.executed

    asyncio.run(scenario())
    assert calls == 1


def test_empty_release_burst_response_keeps_later_offsets(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    service.config = service.config.model_copy(
        update={
            "polling": BiliPollingConfig(
                boost_windows=[
                    BiliBoostWindow(
                        start="10:00:00",
                        end="11:00:00",
                        interval_minutes=60,
                        offset_seconds=[0, 5, 10, 15],
                    )
                ]
            )
        }
    )
    calls = 0

    async def fake_check_logic(*_args: object, **_kwargs: object) -> MonitorCheckResult:
        nonlocal calls
        calls += 1
        return MonitorCheckResult(executed=True, valid_response=False)

    monkeypatch.setattr(monitor_module, "_do_check_logic", fake_check_logic)

    async def scenario() -> None:
        for second in (0, 5, 10, 15):
            result = await run_monitor_check(
                service,
                on_auth_invalid=_ignore_auth_invalid,
                send_push=_ignore_push,
                now=datetime(2026, 1, 1, 10, 0, second, tzinfo=timezone.utc),
            )
            assert result.executed

    asyncio.run(scenario())
    assert calls == BOOST_ATTEMPT_COUNT
