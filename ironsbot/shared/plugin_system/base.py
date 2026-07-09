# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class PluginContext:
    """Runtime context passed from a NoneBot matcher adapter to a plugin."""

    matcher: Any | None = None
    state: Any | None = None
    action: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class Plugin(Protocol):
    name: str
    feature: str
    enabled: bool

    async def handle(self, event: Any, context: PluginContext) -> Any:
        """Handle a matched event."""
