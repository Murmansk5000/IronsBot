# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ironsbot.core.time import (
    ObservationTime,
    ScheduledClockTime,
    clock_window_contains,
    daily_time_parts,
    daily_time_parts_with_seconds,
    normalize_daily_time,
    normalize_daily_time_with_seconds,
    second_of_day,
)


def test_observation_keeps_oldest_and_cannot_repair_unknown_evidence() -> None:
    observation = ObservationTime()
    assert observation.fetched_at is None
    oldest = 10.0
    observation.include(20.0)
    observation.include(oldest)
    observation.include(30.0)
    assert observation.fetched_at == oldest
    observation.include(None)
    observation.include(40.0)
    assert observation.fetched_at is None


@pytest.mark.asyncio
async def test_observation_dates_completion_not_start_or_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    clock = [100.0]
    monkeypatch.setattr(
        "ironsbot.core.time.now",
        lambda: datetime.fromtimestamp(clock[0], tz=timezone.utc),
    )
    observation = ObservationTime()

    async def fetch() -> str:
        clock[0] = 200.0
        return "value"

    assert await observation.observe(fetch) == "value"
    assert observation.fetched_at == clock[0]
    for error in (TimeoutError(), asyncio.CancelledError()):

        async def fail(error: BaseException = error) -> None:
            raise error

        with pytest.raises(type(error)):
            await observation.observe(fail)
        assert observation.fetched_at == clock[0]

    never_started = ObservationTime()
    operation = never_started.observe(fetch)
    operation.close()
    assert never_started.fetched_at is None


def test_scheduled_clock_time_normalizes_minute_and_second_precision() -> None:
    assert ScheduledClockTime.parse(
        "7:05", error_message="invalid"
    ) == ScheduledClockTime(7, 5)
    assert normalize_daily_time("7:05", error_message="invalid") == "07:05"
    assert (
        normalize_daily_time_with_seconds("7:05:09", error_message="invalid")
        == "07:05:09"
    )
    assert daily_time_parts("07:05:09") == (7, 5)
    assert daily_time_parts_with_seconds("07:05:09") == (7, 5, 9)
    expected_seconds = 7 * 60 * 60 + 5 * 60 + 9
    assert second_of_day("07:05:09", error_message="invalid") == expected_seconds


@pytest.mark.parametrize("value", ("", "24:00", "07:60", "07:05:60", "7"))
def test_scheduled_clock_time_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="invalid"):
        ScheduledClockTime.parse(value, error_message="invalid")


def test_clock_window_contains_uses_seconds_and_wraps_midnight() -> None:
    assert clock_window_contains(
        datetime(2026, 8, 13, 7, 0, 5, tzinfo=timezone.utc),
        start="07:00:05",
        end="07:00:07",
        error_message="invalid",
    )
    assert not clock_window_contains(
        datetime(2026, 8, 13, 7, 0, 7, tzinfo=timezone.utc),
        start="07:00:05",
        end="07:00:07",
        error_message="invalid",
    )
    assert clock_window_contains(
        datetime(2026, 8, 13, 0, 0, 2, tzinfo=timezone.utc),
        start="23:59:58",
        end="00:00:03",
        error_message="invalid",
    )
