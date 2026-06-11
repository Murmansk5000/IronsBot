# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from nonebot.adapters import Event
    from nonebot.matcher import Matcher


@dataclass(slots=True)
class PluginContext:
    """Runtime context passed from a NoneBot matcher adapter to a plugin."""

    matcher: Matcher | None = None
    state: MutableMapping[str, Any] | None = None
    action: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class Plugin(Protocol):
    name: str
    feature: str
    enabled: bool

    async def handle(self, event: Event, context: PluginContext) -> Any:
        """Handle a matched event."""


PluginBase = Plugin
