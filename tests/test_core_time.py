# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ironsbot.core.time import (
    ScheduledClockTime,
    clock_window_contains,
    daily_time_parts,
    daily_time_parts_with_seconds,
    normalize_daily_time,
    normalize_daily_time_with_seconds,
    second_of_day,
)


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
