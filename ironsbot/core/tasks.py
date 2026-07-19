# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Coroutine

T = TypeVar("T")


class TaskSpawner(Protocol):
    def __call__(
        self,
        coroutine: Coroutine[Any, Any, T],
        *,
        name: str,
    ) -> asyncio.Task[T]: ...
