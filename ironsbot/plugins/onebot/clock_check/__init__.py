# SPDX-License-Identifier: MIT
"""Run the configured read-only host clock diagnostic after bot connection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.plugin_install import PluginContribution, PluginHooks

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def plugin_contribution(
    *,
    startup_check: Callable[[], Awaitable[None]],
) -> PluginContribution:
    return PluginContribution(
        id="clock_startup_check",
        hooks=PluginHooks(
            first_bot_connect=(("clock_startup_check", lambda _bot: startup_check()),),
        ),
    )
