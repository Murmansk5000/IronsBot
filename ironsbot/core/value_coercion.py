# SPDX-License-Identifier: MIT
from typing import Any, cast


def require_int(value: object, *, field: str) -> int:
    """Return a lossless integer or identify the malformed source field."""

    if isinstance(value, bool):
        raise TypeError(field)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(field)
        return int(value)
    if not isinstance(value, str):
        raise TypeError(field)
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(field) from error


def require_bool_flag(value: object, *, field: str) -> bool:
    """Return a published boolean without accepting truthy malformed values."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise ValueError(field)


def coerce_positive_int(value: object) -> int | None:
    try:
        number = int(cast("Any", value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
