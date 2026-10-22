# SPDX-License-Identifier: MIT
"""Shared OneBot wire scalar validation."""

from typing import Annotated, Any

from pydantic import BeforeValidator
from pydantic_core import PydanticCustomError


def _integer(value: Any) -> Any:
    if isinstance(value, bool):
        message = "OneBot integer field cannot be boolean"
        raise PydanticCustomError("onebot_integer", message)
    return value


OneBotInteger = Annotated[int, BeforeValidator(_integer)]
