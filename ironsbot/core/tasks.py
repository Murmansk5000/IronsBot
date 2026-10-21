# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

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
        /,
        *,
        name: str,
    ) -> asyncio.Task[T]: ...


async def run_owned_blocking(
    operation: Callable[[], T], *, spawn: TaskSpawner, name: str
) -> T:
    """Drain a submitted worker before propagating caller cancellation."""
    await asyncio.sleep(0)
    worker = spawn(asyncio.to_thread(operation), name=name)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(worker)
            break
        except asyncio.CancelledError:
            if worker.cancelled():
                raise
            cancelled = True
        except Exception:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result
