# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.semantic_requests import current_semantic_request_trace

if TYPE_CHECKING:
    from collections.abc import Iterator

RECENT_OPERATION_WINDOW_SECONDS = 90.0


@dataclass(slots=True)
class HeadlessOperation:
    label: str
    detail: str
    source: str
    background: bool
    group_id: int | None
    started_at: float
    semantic_action_id: str = ""
    semantic_action_label: str = ""
    semantic_target: str = ""
    semantic_source: str = ""
    semantic_user_id: int | None = None
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
        group_id: int | None = None,
    ) -> Iterator[HeadlessOperation]:
        parent = self._current.get()
        semantic = current_semantic_request_trace()
        operation = HeadlessOperation(
            label=label.strip() or "无头请求",
            detail=detail.strip(),
            source=source.strip() or label.strip() or "无头请求",
            background=background,
            group_id=group_id,
            started_at=time.monotonic(),
            semantic_action_id=(
                "" if semantic is None else semantic.request.action.id
            ),
            semantic_action_label=(
                "" if semantic is None else semantic.request.action.label
            ),
            semantic_target=(
                "" if semantic is None else semantic.request.target.display
            ),
            semantic_source=(
                "" if semantic is None else semantic.request.source.value
            ),
            semantic_user_id=(None if semantic is None else semantic.user_id),
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
        return self._format(operation)

    def format_current(self) -> str:
        """Describe the operation that is issuing a socket request right now."""
        operation = self._current.get()
        return self._format(operation) if operation is not None else ""

    def format_recent_semantic(self) -> str:
        operation = self._recent(
            now=None,
            window_seconds=RECENT_OPERATION_WINDOW_SECONDS,
        )
        if operation is None or not operation.semantic_action_id:
            return ""
        user = (
            ""
            if operation.semantic_user_id is None
            else f"，QQ：{operation.semantic_user_id}"
        )
        return (
            f"{operation.semantic_action_label}"
            f"（{operation.semantic_action_id}）"
            f"：{operation.semantic_target}"
            f"（来源：{operation.semantic_source}{user}）"
        )

    @staticmethod
    def _format(operation: HeadlessOperation) -> str:
        detail = f"：{operation.detail}" if operation.detail else ""
        kind = "后台" if operation.background else "用户"
        group = f"，群：{operation.group_id}" if operation.group_id is not None else ""
        return f"{operation.label}{detail}（{kind}操作{group}）"

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
