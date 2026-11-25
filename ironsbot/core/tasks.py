# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterator

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


_request_start_deadline: ContextVar[OperationDeadline | None] = ContextVar(
    "request_start_deadline", default=None
)


@contextmanager
def request_start_deadline(deadline: OperationDeadline) -> Iterator[None]:
    token = _request_start_deadline.set(deadline)
    try:
        yield
    finally:
        _request_start_deadline.reset(token)


def check_request_start_deadline() -> None:
    deadline = _request_start_deadline.get()
    if deadline is not None and not deadline.remaining():
        raise TimeoutError


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
    return await run_owned_operation(
        lambda: asyncio.to_thread(operation), spawn=spawn, name=name
    )


async def run_owned_operation(
    operation: Callable[[], Coroutine[Any, Any, T]], *, spawn: TaskSpawner, name: str
) -> T:
    """Finish an accepted operation before propagating caller cancellation."""
    await asyncio.sleep(0)
    coroutine = operation()
    try:
        worker = spawn(coroutine, name=name)
    except BaseException:
        coroutine.close()
        raise
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
