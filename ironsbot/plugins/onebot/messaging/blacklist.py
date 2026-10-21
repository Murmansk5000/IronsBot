# SPDX-License-Identifier: MIT
"""Feature ownership for the shared silent input policy; no native matcher."""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    PluginContribution,
    active_plugin_install_context,
)

__plugin_meta__ = PluginMetadata(
    name="会话黑名单",
    description="静默拦截配置的用户或群会话。",
    usage="由 feature 配置管理，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution() -> PluginContribution:
    """Declare policy ownership without registering a second input path."""

    return PluginContribution(
        id="conversation_blacklist",
        features=frozenset({Feature.BLACKLIST}),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(),
    )
