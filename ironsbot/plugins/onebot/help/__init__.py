# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import HelpEntry, PluginContribution
from ironsbot.services.help_commands import help_command_contracts
from ironsbot.services.help_visibility import always_help_visible


def plugin_contribution() -> PluginContribution:
    """Declare the help menu against the frozen application contribution view."""

    return PluginContribution(
        id="help",
        features=frozenset({Feature.HELP}),
        help=HelpEntry(
            name="帮助",
            description="按当前群/私聊权限显示可用功能",
            group="core",
            order=10,
            visible=always_help_visible,
        ),
        commands=help_command_contracts(),
    )
