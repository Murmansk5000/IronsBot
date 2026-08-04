# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.runtime.plugins import (
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.scheduler import Scheduler

__plugin_meta__ = PluginMetadata(
    name="无头客户端连接检查",
    description="在启动后检查游戏连接，并按配置安排无头客户端重连。",
    usage="后台运行插件，无用户指令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


async def check_headless_on_connect(_bot: Bot, *, service: HeadlessService) -> None:
    await service.check_on_connect()


def plugin_contribution(
    *,
    scheduler: Scheduler,
    service: HeadlessService,
) -> PluginContribution:
    """Declare reconnect scheduling and the initial connection health check."""

    return PluginContribution(
        id="headless_notice",
        hooks=PluginHooks(
            startup=(
                (
                    "headless_reconnect_jobs",
                    partial(service.register_reconnect_jobs, scheduler),
                ),
            ),
            first_bot_connect=(
                (
                    "headless_seer_check",
                    partial(check_headless_on_connect, service=service),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            scheduler=context.scheduler,
            service=context.resources.headless,
        ),
    )
