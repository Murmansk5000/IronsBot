# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class QueryReply:
    leading_text: str = ""
    text: str = ""
    image: bytes | None = None
    image_error: str = ""


@dataclass(frozen=True, slots=True)
class QueryChoice(Generic[T]):
    name: str
    description: str
    value: T
    is_sub_choice: bool = False


@dataclass(frozen=True, slots=True)
class QueryResult(Generic[T]):
    reply: QueryReply | None = None
    choices: tuple[QueryChoice[T], ...] = ()
    message: str = ""
