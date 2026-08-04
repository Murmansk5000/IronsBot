# SPDX-License-Identifier: MIT
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
    from ironsbot.services.operations.scheduled_restart import ScheduledRestartService
    from ironsbot.services.operations.scheduler import Scheduler

__plugin_meta__ = PluginMetadata(
    name="定时重启",
    description="按配置时间重启机器人进程。",
    usage="后台运行插件，无用户指令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


def plugin_contribution(
    *,
    scheduler: Scheduler,
    service: ScheduledRestartService,
) -> PluginContribution:
    """Declare the configured scheduled process restart hook."""

    return PluginContribution(
        id="scheduled_restart",
        hooks=PluginHooks(
            startup=(
                (
                    "scheduled_restart_jobs",
                    partial(service.register_jobs, scheduler),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            scheduler=context.scheduler,
            service=context.resources.scheduled_restart,
        ),
    )
