# SPDX-License-Identifier: MIT
"""Narrow extension point for configuration-backed scheduled messages."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date


@dataclass(frozen=True, slots=True)
class ScheduledRenderRequest:
    today: date
    messages: tuple[str, ...]
    parameters: Mapping[str, str]


ScheduledMessageRenderer = Callable[[ScheduledRenderRequest], tuple[str, ...]]


@dataclass(slots=True)
class ScheduleRendererRegistry:
    _renderers: dict[str, ScheduledMessageRenderer] = field(default_factory=dict)

    def register(self, name: str, renderer: ScheduledMessageRenderer) -> None:
        if not name or name in self._renderers:
            msg = f"duplicate or empty scheduled message renderer: {name}"
            raise ValueError(msg)
        self._renderers[name] = renderer

    def render(
        self, name: str, request: ScheduledRenderRequest
    ) -> tuple[str, ...] | None:
        renderer = self._renderers.get(name)
        return None if renderer is None else renderer(request)
