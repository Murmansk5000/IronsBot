# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.integrations.process import terminate_bot_process
from ironsbot.plugins.operations.restart import register_restart_jobs
from ironsbot.runtime.plugins import (
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)

if TYPE_CHECKING:
    from ironsbot.config.models.operations import RestartConfig
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
    config: RestartConfig,
    scheduler: Scheduler,
) -> PluginContribution:
    """Declare the configured scheduled process restart hook."""

    restart_times = (
        tuple(config.parsed_restart_times) if config.enabled else ()
    )
    return PluginContribution(
        id="scheduled_restart",
        hooks=PluginHooks(
            startup=(
                (
                    "scheduled_restart_jobs",
                    partial(
                        register_restart_jobs,
                        scheduler,
                        restart_times=restart_times,
                        grace_seconds=config.grace_seconds,
                        restart_process=partial(
                            terminate_bot_process,
                            signal_parent=config.signal_parent,
                            reason="scheduled bot restart",
                        ),
                    ),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            config=context.settings.operations.restart,
            scheduler=context.scheduler,
        ),
    )
