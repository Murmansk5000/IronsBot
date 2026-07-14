# SPDX-License-Identifier: MIT
from typing import Any, cast


def coerce_positive_int(value: object) -> int | None:
    try:
        number = int(cast("Any", value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
