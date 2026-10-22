# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.plugin_install import (
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.services.operations.startup_delivery import send_startup_notice

if TYPE_CHECKING:
    from ironsbot.config.models.operations import StartupConfig
    from ironsbot.services.operations.startup import StartupNoticeService

__plugin_meta__ = PluginMetadata(
    name="启动通知",
    description="在首个机器人连接后汇总发送启动状态通知。",
    usage="后台运行插件，无用户指令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution(
    *,
    service: StartupNoticeService,
    config: StartupConfig,
) -> PluginContribution:
    """Declare the first-connection startup notice lifecycle hook."""

    return PluginContribution(
        id="startup_notice",
        hooks=PluginHooks(
            first_bot_connect=(
                (
                    "startup_notice",
                    lambda _account: send_startup_notice(service, config),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.startup_notice,
            config=context.settings.operations.startup_notice,
        ),
    )
