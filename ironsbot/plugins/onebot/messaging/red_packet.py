# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.core.plugin_install import PluginContribution


def plugin_contribution() -> PluginContribution:
    """Declare availability; composition binds the shared passive service."""
    return PluginContribution(id="red_packet_notice")
