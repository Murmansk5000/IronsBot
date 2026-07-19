# SPDX-License-Identifier: MIT
"""Pure normalization helpers for command and configuration values."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Annotated, Any, TypeVar, cast

from pydantic import BeforeValidator

T = TypeVar("T")
DEFAULT_COMMAND_PREFIXES = ("/",)
_CONFIRMATION_REPLIES = frozenset(("是", "yes", "y", "确认", "确定"))
_DECLINE_REPLIES = frozenset(("否", "no", "n", "取消"))


def normalize_command_text(text: str) -> str:
    return "".join(text.split()).lower()


def strip_command_prefix(
    text: str,
    prefixes: Iterable[str] = DEFAULT_COMMAND_PREFIXES,
) -> str | None:
    stripped = text.strip()
    for prefix in prefixes:
        if prefix and stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def command_text_matches(text: str, commands: Iterable[str]) -> bool:
    normalized = normalize_command_text(text)
    return normalized in {
        normalize_command_text(command)
        for command in commands
    }


def parse_confirmation(text: str) -> bool | None:
    normalized = text.strip().casefold()
    if normalized in _CONFIRMATION_REPLIES:
        return True
    if normalized in _DECLINE_REPLIES:
        return False
    return None


def unique_items(values: Iterable[T]) -> list[T]:
    return list(dict.fromkeys(values))


def csv_items(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def json_object(value: object, *, name: str = "config") -> dict[str, Any]:
    if value is None or value == "":
        return {}

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        value = json.loads(text)

    if isinstance(value, Mapping):
        return dict(value)

    msg = f"{name} must be a JSON object"
    raise TypeError(msg)


def json_array(value: object, *, name: str = "config") -> list[Any]:
    if value is None or value == "":
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        value = json.loads(text)

    if isinstance(value, list):
        return value

    msg = f"{name} must be a JSON array"
    raise TypeError(msg)


def string_list(value: object) -> list[str]:
    if value is None or value == "":
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        raw_items: Iterable[object] = (
            json_array(text, name="string list")
            if text.startswith("[")
            else csv_items(text)
        )
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        raw_items = value
    else:
        return []

    return unique_items(
        item for raw_item in raw_items if (item := str(raw_item).strip())
    )


def int_list(value: object) -> list[int]:
    if value is None or value == "":
        return []

    if isinstance(value, int):
        return [value]

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        raw_items: Iterable[object] = (
            json_array(text, name="integer list")
            if text.startswith("[")
            else csv_items(text)
        )
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        raw_items = value
    else:
        return []

    return unique_items(int(cast("Any", item)) for item in raw_items)


def positive_int_list(value: object) -> list[int]:
    return [item for item in int_list(value) if item > 0]


NormalizedStringList = Annotated[list[str], BeforeValidator(string_list)]
NormalizedStringSet = Annotated[set[str], BeforeValidator(string_list)]
NormalizedStringFrozenSet = Annotated[
    frozenset[str],
    BeforeValidator(string_list),
]
NormalizedIntList = Annotated[list[int], BeforeValidator(int_list)]
