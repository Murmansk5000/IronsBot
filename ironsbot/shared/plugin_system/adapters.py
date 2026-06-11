# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import PluginContext
from .registry import plugin_registry

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from nonebot.adapters import Event
    from nonebot.matcher import Matcher


async def dispatch_plugin(
    *,
    plugin_name: str,
    event: Event,
    matcher: Matcher | None = None,
    state: MutableMapping[str, Any] | None = None,
    action: str | None = None,
    **data: Any,
) -> Any:
    context = PluginContext(
        matcher=matcher,
        state=state,
        action=action,
        data=data,
    )
    return await plugin_registry.dispatch(
        event,
        context,
        plugin_name=plugin_name,
    )
