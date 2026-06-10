# SPDX-License-Identifier: MIT
import json
from collections.abc import Iterable, Mapping
from typing import Any, TypeVar

T = TypeVar("T")


def unique_items(values: Iterable[T]) -> list[T]:
    return list(dict.fromkeys(values))


def csv_items(text: str) -> list[str]:
    return [
        item.strip()
        for item in text.split(",")
        if item.strip()
    ]


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


def nested_json_config(
    value: object,
    model_type: type[T],
    *,
    name: str,
) -> object:
    if value is None or value == "":
        return model_type()

    if isinstance(value, str):
        return json_object(value, name=name)

    return value


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
        item
        for raw_item in raw_items
        if (item := str(raw_item).strip())
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

    return unique_items(int(item) for item in raw_items)


def positive_int_list(value: object) -> list[int]:
    return [
        item
        for item in int_list(value)
        if item > 0
    ]
