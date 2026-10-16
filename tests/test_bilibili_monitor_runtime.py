from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.core.bilibili import BiliBoostWindow, BiliPollingConfig
from ironsbot.core.time import TZ_CN
from ironsbot.services.bilibili import monitor as monitor_module
from ironsbot.services.bilibili.monitor import (
    SEER_OFFICIAL_UID,
    MonitorCheckResult,
    run_monitor_check,
)
from ironsbot.services.bilibili.runtime import (
    BILIBILI_REFRESH_BUSY,
    BILIBILI_REFRESH_COMPLETED,
    BILIBILI_REFRESH_FAILED,
    BilibiliMonitorService,
)
from tests.helpers.bilibili import build_test_bilibili_service

BOOST_ATTEMPT_COUNT = 4

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

    from ironsbot.services.bilibili.target_models import BiliPushTargets
    from ironsbot.services.operations.scheduler import Scheduler


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


async def _ignore_auth_invalid(_reason: str) -> None:
    return None


async def _ignore_push(
    _item: dict[str, Any],
    _pub_ts: int,
    _author_mid: int,
    _targets: BiliPushTargets,
    _categories: tuple[str, ...],
) -> None:
    return None


@pytest.mark.parametrize(
    ("result", "expected"),
    (
        (MonitorCheckResult(), BILIBILI_REFRESH_BUSY),
        (
            MonitorCheckResult(executed=True, valid_response=False),
            BILIBILI_REFRESH_FAILED,
        ),
        (
            MonitorCheckResult(executed=True, valid_response=True),
            BILIBILI_REFRESH_COMPLETED,
        ),
    ),
)
def test_manual_refresh_classifies_monitor_result(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    result: MonitorCheckResult,
    expected: str,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    monitor = BilibiliMonitorService(service, _ignore_auth_invalid, _ignore_push)
    calls: list[tuple[bool, bool]] = []

    async def check(
        _self: BilibiliMonitorService,
        *,
        is_startup_check: bool = False,
        force: bool = False,
    ) -> MonitorCheckResult:
        calls.append((is_startup_check, force))
        return result

    monkeypatch.setattr(BilibiliMonitorService, "check", check)

    assert asyncio.run(monitor.manual_refresh()) == expected
    assert calls == [(True, True)]


def test_bili_monitor_service_registers_second_precision_scheduler_job(
    tmp_path: Path,
) -> None:
    scheduler = FakeScheduler()
    service = build_test_bilibili_service(tmp_path)
    service.config = service.config.model_copy(
        update={"polling": BiliPollingConfig(boost_windows=[])}
    )
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
        "timezone": TZ_CN,
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
    assert all(job["timezone"] == TZ_CN for job in scheduler.jobs[1:])


def test_bili_monitor_registers_default_half_hour_bursts_once(tmp_path: Path) -> None:
    scheduler = FakeScheduler()
    service = build_test_bilibili_service(tmp_path)
    monitor = BilibiliMonitorService(service, _ignore_auth_invalid, _ignore_push)

    asyncio.run(monitor.register_job(cast("Scheduler", scheduler)))

    boost_job_times = [
        (job["hour"], job["minute"], job["second"]) for job in scheduler.jobs[1:]
    ]
    assert len(boost_job_times) == 21 * 3
    assert boost_job_times[:3] == [(10, 0, 1), (10, 0, 2), (10, 0, 10)]
    assert boost_job_times[-3:] == [(20, 0, 1), (20, 0, 2), (20, 0, 10)]
    assert all(
        second != service.config.polling.check_second
        for _, _, second in boost_job_times
    )


@pytest.mark.parametrize("uid", [None, 912345678, SEER_OFFICIAL_UID])
def test_only_seer_discovery_stops_the_rest_of_its_release_burst(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    uid: int | None,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    service.config = service.config.model_copy(update={"polling": BiliPollingConfig()})
    calls = 0

    async def fake_check_logic(*_args: object, **_kwargs: object) -> MonitorCheckResult:
        nonlocal calls
        calls += 1
        return MonitorCheckResult(
            executed=True,
            valid_response=True,
            discovered_new=uid is not None,
            discovered_uids=frozenset((uid,)) if uid is not None else frozenset(),
        )

    monkeypatch.setattr(monitor_module, "_do_check_logic", fake_check_logic)

    async def scenario() -> None:
        for second in (1, 2, 5, 10):
            now = datetime(2026, 1, 1, 2, 0, second, tzinfo=timezone.utc)
            result = await run_monitor_check(
                service,
                on_auth_invalid=_ignore_auth_invalid,
                send_push=_ignore_push,
                now=now,
            )
            assert result.executed == (second == 1 or uid != SEER_OFFICIAL_UID)

    asyncio.run(scenario())
    assert calls == (1 if uid == SEER_OFFICIAL_UID else BOOST_ATTEMPT_COUNT)


def test_overlapping_burst_checks_preserve_pending_and_future_offsets(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    calls = 0

    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def check(*_args: object, **_kwargs: object) -> MonitorCheckResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            return MonitorCheckResult(
                executed=True,
                valid_response=True,
                discovered_new=True,
                discovered_uids=frozenset(
                    (SEER_OFFICIAL_UID if calls == BOOST_ATTEMPT_COUNT else 912345678,)
                ),
            )

        monkeypatch.setattr(monitor_module, "_do_check_logic", check)

        async def at(second: int) -> MonitorCheckResult:
            return await run_monitor_check(
                service,
                on_auth_invalid=_ignore_auth_invalid,
                send_push=_ignore_push,
                now=datetime(2026, 1, 1, 2, 0, second, tzinfo=timezone.utc),
            )

        first = asyncio.create_task(at(1))
        overlapping_checks = 2
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert not (await at(2)).executed
        finally:
            release.set()
        await asyncio.wait_for(first, 1)
        assert calls == overlapping_checks
        assert not service.pending_boost_slots
        assert (await at(5)).executed
        assert (await at(10)).executed
        assert not (await at(10)).executed
        assert calls == BOOST_ATTEMPT_COUNT

    asyncio.run(scenario())


def test_empty_release_burst_response_keeps_later_offsets(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    service = build_test_bilibili_service(tmp_path)
    service.config = service.config.model_copy(update={"polling": BiliPollingConfig()})
    calls = 0

    async def fake_check_logic(*_args: object, **_kwargs: object) -> MonitorCheckResult:
        nonlocal calls
        calls += 1
        return MonitorCheckResult(executed=True, valid_response=False)

    monkeypatch.setattr(monitor_module, "_do_check_logic", fake_check_logic)

    async def scenario() -> None:
        for second in (1, 2, 5, 10):
            result = await run_monitor_check(
                service,
                on_auth_invalid=_ignore_auth_invalid,
                send_push=_ignore_push,
                now=datetime(2026, 1, 1, 2, 0, second, tzinfo=timezone.utc),
            )
            assert result.executed

    asyncio.run(scenario())
    assert calls == BOOST_ATTEMPT_COUNT
