# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

from typing_extensions import Self

from ironsbot.app import clock_check
from ironsbot.config.models.settings import RuntimeSchedulerConfig
from ironsbot.integrations.http.clock import ClockCheckSample, check_clock_drift

if TYPE_CHECKING:
    from pytest import MonkeyPatch


class FakeResponse:
    def __init__(self, date: str) -> None:
        self.headers = {"Date": date}


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.urls: list[str] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def head(self, url: str) -> FakeResponse:
        self.urls.append(url)
        return self.response


class NoticeRecorder:
    def __init__(self) -> None:
        self.parts: list[tuple[str, str, str | None]] = []

    def add(self, key: str, action: str, message: str | None) -> None:
        self.parts.append((key, action, message))


def test_clock_check_uses_request_midpoint_without_changing_time() -> None:
    started = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
    instants = iter((started, started + timedelta(seconds=2)))
    client = FakeClient(FakeResponse("Tue, 12 Aug 2026 12:00:06 GMT"))

    samples = asyncio.run(
        check_clock_drift(
            timeout_seconds=3,
            urls=("https://clock.example",),
            client_factory=cast("Any", lambda **_: client),
            now=lambda: next(instants),
        )
    )

    assert samples == (
        ClockCheckSample("https://clock.example", 5.0),
    )
    assert client.urls == ["https://clock.example"]


def test_clock_check_adds_startup_notice_only_above_threshold(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_check(**_: Any) -> tuple[ClockCheckSample, ...]:
        return (
            ClockCheckSample("https://one.example", 4.0),
            ClockCheckSample("https://two.example", 6.0),
        )

    monkeypatch.setattr(clock_check, "check_clock_drift", fake_check)
    notices = NoticeRecorder()

    asyncio.run(
        clock_check.check_configured_clock(
            RuntimeSchedulerConfig(clock_warning_threshold_seconds=3),
            notices,  # type: ignore[arg-type]
        )
    )

    assert len(notices.parts) == 1
    key, action, message = notices.parts[0]
    assert key == "startup_clock_check"
    assert action == "startup clock check"
    assert message is not None and "5.00s slow" in message


def test_clock_check_can_be_disabled(monkeypatch: MonkeyPatch) -> None:
    called = False

    async def fake_check(**_: Any) -> tuple[ClockCheckSample, ...]:
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(clock_check, "check_clock_drift", fake_check)

    asyncio.run(
        clock_check.check_configured_clock(
            RuntimeSchedulerConfig(clock_check_on_startup=False),
            NoticeRecorder(),  # type: ignore[arg-type]
        )
    )

    assert not called


def test_clock_check_allows_every_time_source_to_fail(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_check(**_: Any) -> tuple[ClockCheckSample, ...]:
        return ()

    monkeypatch.setattr(clock_check, "check_clock_drift", fake_check)
    notices = NoticeRecorder()

    asyncio.run(
        clock_check.check_configured_clock(
            RuntimeSchedulerConfig(),
            notices,  # type: ignore[arg-type]
        )
    )

    assert notices.parts == []
