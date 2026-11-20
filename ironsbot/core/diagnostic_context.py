# SPDX-License-Identifier: MIT
"""Execution-only diagnostic metadata, independent from request identity."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_CURRENT: ContextVar[tuple[str, str]] = ContextVar(
    "diagnostic_operation", default=("", "")
)


def current_diagnostic_operation() -> tuple[str, str]:
    return _CURRENT.get()


@contextmanager
def diagnostic_operation(action: str, command: str = "") -> Iterator[None]:
    token = _CURRENT.set((action, command))
    try:
        yield
    except Exception as error:
        error.__dict__.setdefault("diagnostic_operation", (action, command))
        raise
    finally:
        _CURRENT.reset(token)
