from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from ironsbot.core.bilibili import BiliBoostWindow, BiliPollingConfig
from ironsbot.services.bilibili import monitor as monitor_module
from ironsbot.services.bilibili.monitor import MonitorCheckResult, run_monitor_check
from ironsbot.services.bilibili.runtime import BilibiliMonitorService
from tests.helpers.bilibili import build_test_bilibili_service

EXPECTED_CATCH_UP_CHECK_COUNT = 2
EXPECTED_BOOST_JOB_COUNT = 42
BOOST_SAMPLE_HOUR = 17
BOOST_SAMPLE_MINUTE = 30
BOOST_SAMPLE_SECOND = 15
BOOST_ATTEMPT_COUNT = 4

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

    regular_job = scheduler.jobs[0]
    func = regular_job.pop("func")
    assert func == monitor.check
    assert regular_job == {
        "trigger": "cron",
        "id": "bilibili_monitor_auto_check",
        "replace_existing": True,
        "minute": "*",
        "second": 5,
    }
    boost_jobs = scheduler.jobs[1:]
    assert len(boost_jobs) == EXPECTED_BOOST_JOB_COUNT
    assert all(job["func"] == monitor.check for job in boost_jobs)
    assert {job["second"] for job in boost_jobs} == {0, 10, 15}
    assert any(
        job["hour"] == BOOST_SAMPLE_HOUR
        and job["minute"] == BOOST_SAMPLE_MINUTE
        and job["second"] == BOOST_SAMPLE_SECOND
        for job in boost_jobs
    )


def test_running_monitor_coalesces_missed_tick_into_one_catch_up(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def fake_check_logic(
        *_args: object,
        **_kwargs: object,
    ) -> MonitorCheckResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        return MonitorCheckResult(executed=True, valid_response=True)

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


def _boost_polling() -> BiliPollingConfig:
    return BiliPollingConfig(
        default_minutes=30,
        boost_windows=[
            BiliBoostWindow(
                start="10:00:00",
                end="11:00:00",
                interval_minutes=60,
                offset_seconds=[0, 5, 10, 15],
            )
        ],
    )


def test_new_dynamic_ends_current_release_burst(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    service.config = service.config.model_copy(update={"polling": _boost_polling()})
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


def test_empty_or_failed_burst_response_keeps_later_offsets(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    service.config = service.config.model_copy(update={"polling": _boost_polling()})
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


def test_completed_burst_drops_pending_same_slot_attempt(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    service.config = service.config.model_copy(update={"polling": _boost_polling()})
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def fake_check_logic(*_args: object, **_kwargs: object) -> MonitorCheckResult:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return MonitorCheckResult(
            executed=True,
            valid_response=True,
            discovered_new=True,
        )

    monkeypatch.setattr(monitor_module, "_do_check_logic", fake_check_logic)

    async def scenario() -> None:
        first = asyncio.create_task(
            run_monitor_check(
                service,
                on_auth_invalid=_ignore_auth_invalid,
                send_push=_ignore_push,
                now=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            )
        )
        await started.wait()
        queued = await run_monitor_check(
            service,
            on_auth_invalid=_ignore_auth_invalid,
            send_push=_ignore_push,
            now=datetime(2026, 1, 1, 10, 0, 5, tzinfo=timezone.utc),
        )
        assert not queued.executed
        release.set()
        assert (await first).discovered_new

    asyncio.run(scenario())
    assert calls == 1
