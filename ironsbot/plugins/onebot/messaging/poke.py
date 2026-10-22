# SPDX-License-Identifier: MIT
"""Declare poke availability; the transport ingress binds its shared service."""

from __future__ import annotations

from ironsbot.core.plugin_install import PluginContribution


def plugin_contribution() -> PluginContribution:
    return PluginContribution(id="poke_reply")
