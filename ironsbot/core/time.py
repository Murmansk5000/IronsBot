# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ironsbot.core.commands import csv_items, json_array

TZ_CN = timezone(timedelta(hours=8))
TIME_PART_COUNT = 2
TIME_PART_COUNT_WITH_SECONDS = 3
MIN_HOUR = 0
MAX_HOUR = 23
MIN_MINUTE = 0
MAX_MINUTE = 59
MIN_SECOND = 0
MAX_SECOND = 59
FULLWIDTH_COMMA = "，"
IDEOGRAPHIC_COMMA = "、"
FULLWIDTH_SEMICOLON = "；"


def now(tz: timezone | None = None) -> datetime:
    if tz is None:
        return datetime.now(timezone.utc).astimezone()
    return datetime.now(tz=tz)


@dataclass(frozen=True, slots=True, order=True)
class ScheduledClockTime:
    """A local wall-clock time used by recurring jobs and time windows."""

    hour: int
    minute: int
    second: int = 0

    @classmethod
    def parse(
        cls,
        value: object,
        *,
        error_message: str,
    ) -> ScheduledClockTime:
        text = str(value).strip()
        parts = text.split(":")
        if len(parts) not in {TIME_PART_COUNT, TIME_PART_COUNT_WITH_SECONDS}:
            raise ValueError(error_message)

        try:
            hour = int(parts[0])
            minute = int(parts[1])
            second = int(parts[2]) if len(parts) == TIME_PART_COUNT_WITH_SECONDS else 0
        except ValueError as exc:
            raise ValueError(error_message) from exc

        if (
            not MIN_HOUR <= hour <= MAX_HOUR
            or not MIN_MINUTE <= minute <= MAX_MINUTE
            or not MIN_SECOND <= second <= MAX_SECOND
        ):
            raise ValueError(error_message)
        return cls(hour, minute, second)

    @property
    def seconds_of_day(self) -> int:
        return (self.hour * 60 + self.minute) * 60 + self.second

    def cron_kwargs(self) -> dict[str, int]:
        return {"hour": self.hour, "minute": self.minute, "second": self.second}

    def __str__(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}:{self.second:02d}"


def scheduled_clock_time(value: object, *, error_message: str) -> ScheduledClockTime:
    return ScheduledClockTime.parse(value, error_message=error_message)


def normalize_daily_time(value: object, *, error_message: str) -> str:
    """Normalize legacy HH:MM input to the canonical HH:MM:SS representation."""
    return str(scheduled_clock_time(value, error_message=error_message))


def daily_time_parts(
    value: object,
    *,
    error_message: str = "daily time must use HH:MM",
) -> tuple[int, int]:
    clock_time = scheduled_clock_time(value, error_message=error_message)
    return clock_time.hour, clock_time.minute


def normalize_daily_time_with_seconds(
    value: object,
    *,
    error_message: str,
) -> str:
    return normalize_daily_time(value, error_message=error_message)


def daily_time_parts_with_seconds(
    value: object,
    *,
    error_message: str = "daily time must use HH:MM or HH:MM:SS",
) -> tuple[int, int, int]:
    clock_time = scheduled_clock_time(value, error_message=error_message)
    return clock_time.hour, clock_time.minute, clock_time.second


def minute_of_day(value: object, *, error_message: str) -> int:
    return scheduled_clock_time(value, error_message=error_message).seconds_of_day // 60


def second_of_day(value: object, *, error_message: str) -> int:
    return scheduled_clock_time(value, error_message=error_message).seconds_of_day


def clock_window_contains(
    moment: datetime,
    *,
    start: str,
    end: str,
    error_message: str,
) -> bool:
    """Return whether a moment falls in [start, end), including midnight wrap."""
    current = (moment.hour * 60 + moment.minute) * 60 + moment.second
    start_second = second_of_day(start, error_message=error_message)
    end_second = second_of_day(end, error_message=error_message)
    if start_second <= end_second:
        return start_second <= current < end_second
    return current >= start_second or current < end_second


def normalized_daily_times(
    value: object,
    *,
    error_message: str,
) -> list[str]:
    return [
        normalize_daily_time(item, error_message=error_message)
        for item in split_daily_time_values(value, error_message=error_message)
    ]


def normalized_daily_time_csv(value: object, *, error_message: str) -> str:
    return ",".join(
        sorted(
            dict.fromkeys(
                normalized_daily_times(value, error_message=error_message)
            )
        )
    )


def split_daily_time_values(
    value: object,
    *,
    error_message: str,
) -> list[object]:
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []

        if text.startswith("["):
            try:
                return split_daily_time_values(
                    json_array(text, name="daily time list"),
                    error_message=error_message,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(error_message) from exc

        normalized = (
            text
            .replace(FULLWIDTH_COMMA, ",")
            .replace(IDEOGRAPHIC_COMMA, ",")
            .replace(FULLWIDTH_SEMICOLON, ",")
        )
        items: list[object] = list(csv_items(normalized))
        return items

    if isinstance(value, Sequence):
        return list(value)

    return [value]
