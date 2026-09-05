# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Coroutine

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class OperationDeadline:
    """Share one monotonic budget across sequential and concurrent stages."""

    expires_at: float

    @classmethod
    def after(cls, seconds: float) -> OperationDeadline:
        return cls(monotonic() + max(0.0, seconds))

    def remaining(self, cap: float | None = None) -> float:
        seconds = max(0.0, self.expires_at - monotonic())
        return seconds if cap is None else max(0.0, min(seconds, cap))


class TaskSpawner(Protocol):
    def __call__(
        self,
        coroutine: Coroutine[Any, Any, T],
        *,
        name: str,
    ) -> asyncio.Task[T]: ...
