# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral render outcomes and the sole text-fallback contract."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

RenderStage = Literal["prepare", "queue", "render"]


@dataclass(slots=True)
class RenderExecution:
    stage: RenderStage = "prepare"
    degraded: bool = False
    writes: list[Callable[[], None]] = field(default_factory=list)
    cache_key: str = ""


current_render: ContextVar[RenderExecution | None] = ContextVar(
    "current_render", default=None
)


def mark_render_degraded() -> None:
    if (execution := current_render.get()) is not None:
        execution.degraded = True


def publish_render_cache(write: Callable[[], None]) -> None:
    if (execution := current_render.get()) is not None:
        execution.writes.append(write)
    else:
        write()


@dataclass(frozen=True, slots=True)
class RenderRequest:
    template: str
    fallback_text: str = ""
    data_version: str = ""
    cache_key: str = ""


@dataclass(frozen=True, slots=True)
class RenderResult:
    request: RenderRequest
    image: bytes | None
    status: Literal["complete", "degraded", "failed"]
    failure_stage: RenderStage | None = None
    exception_type: str | None = None

    @property
    def fallback_text(self) -> str:
        if not self.request.fallback_text:
            return "图片生成失败，请稍后重试。"
        notice = "图片生成失败，已切换为文字。"
        return f"{notice}\n{self.request.fallback_text}".strip()

    def require_image(self) -> bytes:
        if self.image is None:
            raise RenderFailureError(self)
        return self.image


class RenderFailureError(RuntimeError):
    """A confirmed generation failure, never an upload or delivery failure."""

    def __init__(self, result: RenderResult) -> None:
        self.result = result
        super().__init__(f"render {result.failure_stage}: {result.exception_type}")
