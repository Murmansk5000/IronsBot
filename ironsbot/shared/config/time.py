# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Sequence

from ironsbot.shared.config.parsing import csv_items, json_array

TIME_PART_COUNT = 2
MIN_HOUR = 0
MAX_HOUR = 23
MIN_MINUTE = 0
MAX_MINUTE = 59
FULLWIDTH_COMMA = "，"
IDEOGRAPHIC_COMMA = "、"
FULLWIDTH_SEMICOLON = "；"


def normalize_daily_time(value: object, *, error_message: str) -> str:
    text = str(value).strip()
    parts = text.split(":")
    if len(parts) != TIME_PART_COUNT:
        raise ValueError(error_message)

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError(error_message) from exc

    if not MIN_HOUR <= hour <= MAX_HOUR or not MIN_MINUTE <= minute <= MAX_MINUTE:
        raise ValueError(error_message)

    return f"{hour:02d}:{minute:02d}"


def daily_time_parts(value: object, *, error_message: str) -> tuple[int, int]:
    normalized = normalize_daily_time(value, error_message=error_message)
    hour_text, minute_text = normalized.split(":", maxsplit=1)
    return int(hour_text), int(minute_text)


def minute_of_day(value: object, *, error_message: str) -> int:
    hour, minute = daily_time_parts(value, error_message=error_message)
    return hour * 60 + minute


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
