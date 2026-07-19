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


class HeadlessOperationTracker:
    def __init__(self) -> None:
        self._current: ContextVar[HeadlessOperation | None] = ContextVar(
            "headless_seer_operation",
            default=None,
        )
        self._active: dict[int, HeadlessOperation] = {}
        self._last: HeadlessOperation | None = None

    @contextmanager
    def track(
        self,
        label: str,
        detail: str = "",
        *,
        source: str = "",
        background: bool = False,
    ) -> Iterator[HeadlessOperation]:
        parent = self._current.get()
        operation = HeadlessOperation(
            label=label.strip() or "无头请求",
            detail=detail.strip(),
            source=source.strip() or label.strip() or "无头请求",
            background=background,
            started_at=time.monotonic(),
        )
        token = self._current.set(operation)
        self._active[id(operation)] = operation
        self._last = operation
        try:
            yield operation
        finally:
            operation.ended_at = time.monotonic()
            self._active.pop(id(operation), None)
            self._last = parent or operation
            self._current.reset(token)

    def format_recent(
        self,
        *,
        now: float | None = None,
        window_seconds: float = RECENT_OPERATION_WINDOW_SECONDS,
    ) -> str:
        operation = self._recent(now=now, window_seconds=window_seconds)
        if operation is None:
            return ""
        detail = f"：{operation.detail}" if operation.detail else ""
        kind = "后台" if operation.background else "用户"
        return f"{operation.label}{detail}（{kind}操作）"

    def _recent(
        self,
        *,
        now: float | None,
        window_seconds: float,
    ) -> HeadlessOperation | None:
        current = self._current.get()
        if current is not None:
            return current
        if self._active:
            return max(self._active.values(), key=lambda item: item.started_at)
        if self._last is None:
            return None
        current_time = time.monotonic() if now is None else now
        reference = self._last.ended_at or self._last.started_at
        return self._last if current_time - reference <= window_seconds else None
