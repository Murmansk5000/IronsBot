# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.services.help_commands import help_command_contracts
from ironsbot.services.help_visibility import always_help_visible

__plugin_meta__ = PluginMetadata(
    name="帮助",
    description="按当前会话权限显示可用功能与命令。",
    usage="发送“帮助”。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

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


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(),
    )
