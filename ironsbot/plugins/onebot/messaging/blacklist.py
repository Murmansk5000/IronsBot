# SPDX-License-Identifier: MIT
"""Feature ownership for the shared silent input policy; no native matcher."""

from __future__ import annotations

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import PluginContribution


def plugin_contribution() -> PluginContribution:
    """Declare policy ownership without registering a second input path."""

    return PluginContribution(
        id="conversation_blacklist",
        features=frozenset({Feature.BLACKLIST}),
    )
