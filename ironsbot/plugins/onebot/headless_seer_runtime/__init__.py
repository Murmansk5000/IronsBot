# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.plugin_install import PluginContribution, PluginHooks

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService


def plugin_contribution(*, service: HeadlessService) -> PluginContribution:
    """Declare the long-lived headless client lifecycle."""

    return PluginContribution(
        id="headless_seer",
        hooks=PluginHooks(
            startup=(("headless_seer", service.start),),
            shutdown=(("headless_seer", service.shutdown),),
        ),
    )
