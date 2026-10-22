# SPDX-License-Identifier: MIT
"""Manifest contribution for the Fire Manual promotion feature."""

from __future__ import annotations

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import PluginContribution


def plugin_contribution() -> PluginContribution:
    """Declare feature ownership for the promotion delivery policy."""

    return PluginContribution(
        id="fire_manual_ad",
        features=frozenset({Feature.FIRE_MANUAL_AD}),
    )
