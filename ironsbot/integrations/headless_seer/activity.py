# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

RECENT_OPERATION_WINDOW_SECONDS = 90.0


@dataclass(slots=True)
class HeadlessOperation:
    label: str
    detail: str
    source: str
    background: bool
    started_at: float
    ended_at: float | None = None


@dataclass(slots=True)
class _HeadlessOperationState:
    last_operation: HeadlessOperation | None = None


_current_operation: ContextVar[HeadlessOperation | None] = ContextVar(
    "headless_seer_operation",
    default=None,
)
_active_operations: dict[int, HeadlessOperation] = {}
_operation_state = _HeadlessOperationState()


@contextmanager
def headless_operation(
    label: str,
    detail: str = "",
    *,
    source: str = "",
    background: bool = False,
) -> Iterator[HeadlessOperation]:
    """Record the current logical operation using the headless Seer client.

    The socket reader runs in a different task from the requester, so a plain
    ContextVar is not enough for disconnect diagnostics.  We keep a small
    process-local active/recent operation registry and use it only for notices.
    """

    parent = _current_operation.get()
    operation = HeadlessOperation(
        label=label.strip() or "无头请求",
        detail=detail.strip(),
        source=source.strip() or label.strip() or "无头请求",
        background=background,
        started_at=time.monotonic(),
    )
    token = _current_operation.set(operation)
    _active_operations[id(operation)] = operation
    _operation_state.last_operation = operation
    try:
        yield operation
    finally:
        operation.ended_at = time.monotonic()
        _active_operations.pop(id(operation), None)
        _operation_state.last_operation = operation
        _current_operation.reset(token)
        if parent is not None:
            _operation_state.last_operation = parent


def current_headless_operation() -> HeadlessOperation | None:
    return _current_operation.get()


def recent_headless_operation(
    *,
    now: float | None = None,
    window_seconds: float = RECENT_OPERATION_WINDOW_SECONDS,
) -> HeadlessOperation | None:
    current = current_headless_operation()
    if current is not None:
        return current

    if _active_operations:
        return max(
            _active_operations.values(),
            key=lambda operation: operation.started_at,
        )

    operation = _operation_state.last_operation
    if operation is None:
        return None
    current_time = time.monotonic() if now is None else now
    reference = operation.ended_at or operation.started_at
    if current_time - reference > window_seconds:
        return None
    return operation


def format_headless_operation(operation: HeadlessOperation | None) -> str:
    if operation is None:
        return ""

    detail = f"：{operation.detail}" if operation.detail else ""
    kind = "后台" if operation.background else "用户"
    return f"{operation.label}{detail}（{kind}操作）"


def format_recent_headless_operation() -> str:
    return format_headless_operation(recent_headless_operation())


def reset_headless_operation_state() -> None:
    _active_operations.clear()
    _operation_state.last_operation = None


__all__ = [
    "HeadlessOperation",
    "current_headless_operation",
    "format_headless_operation",
    "format_recent_headless_operation",
    "headless_operation",
    "recent_headless_operation",
    "reset_headless_operation_state",
]
