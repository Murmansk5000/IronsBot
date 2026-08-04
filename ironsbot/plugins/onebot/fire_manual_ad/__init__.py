# SPDX-License-Identifier: MIT
"""Manifest contribution for the Fire Manual promotion feature."""

from __future__ import annotations

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.runtime.plugins import PluginContribution, active_plugin_install_context

__plugin_meta__ = PluginMetadata(
    name="火火手册推广",
    description="按会话功能策略为主动文本推送追加火火手册链接。",
    usage="由 fire_manual_ad feature 配置管理，无直接用户命令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution() -> PluginContribution:
    """Declare feature ownership for the promotion delivery policy."""

    return PluginContribution(
        id="fire_manual_ad",
        features=frozenset({Feature.FIRE_MANUAL_AD}),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(__plugin_meta__, plugin_contribution())
