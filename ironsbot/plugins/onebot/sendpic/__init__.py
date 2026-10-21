# SPDX-License-Identifier: MIT
"""Declarative entrypoint for configured image commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    active_plugin_install_context,
)
from ironsbot.services.messaging.sendpic import sendpic_command_contracts

__plugin_meta__ = PluginMetadata(
    name="图片发送",
    description="发送固定图片或配置的图片库内容。",
    usage="发送已配置的图片口令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from ironsbot.services.messaging.sendpic import SendpicService


def plugin_contribution(*, service: SendpicService) -> PluginContribution:
    """Declare configured image commands."""

    return PluginContribution(
        id="sendpic",
        features=frozenset({Feature.IMAGE}),
        help=HelpEntry(
            name="图片发送",
            description="发送固定图片或配置的图片库内容",
            group="other",
            order=20,
        ),
        commands=sendpic_command_contracts(service),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(service=context.resources.sendpic),
    )
