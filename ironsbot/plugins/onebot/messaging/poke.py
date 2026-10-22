# SPDX-License-Identifier: MIT
"""Declare poke availability; the transport ingress binds its shared service."""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    PluginContribution,
    active_plugin_install_context,
)

__plugin_meta__ = PluginMetadata(
    name="戳一戳回复",
    description="机器人被戳一戳时按会话权限给出可用指令。",
    usage="由机器人戳一戳事件触发，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution() -> PluginContribution:
    return PluginContribution(id="poke_reply")


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(),
    )
