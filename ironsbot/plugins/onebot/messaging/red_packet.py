# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    PluginContribution,
    active_plugin_install_context,
)

__plugin_meta__ = PluginMetadata(
    name="红包提醒",
    description="检测群红包并向管理通知目标发送提醒。",
    usage="由 messaging.red_packet_notice 配置管理，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution() -> PluginContribution:
    """Declare availability; composition binds the shared passive service."""
    return PluginContribution(id="red_packet_notice")


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(),
    )
