# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService

__plugin_meta__ = PluginMetadata(
    name="无头客户端运行时",
    description="管理赛尔号无头客户端的启动与关闭。",
    usage="后台运行插件，无用户指令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution(*, service: HeadlessService) -> PluginContribution:
    """Declare the long-lived headless client lifecycle."""

    return PluginContribution(
        id="headless_seer",
        hooks=PluginHooks(
            startup=(("headless_seer", service.start),),
            shutdown=(("headless_seer", service.shutdown),),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(service=context.resources.headless),
    )
