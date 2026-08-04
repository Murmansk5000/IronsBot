# SPDX-License-Identifier: MIT
"""Bind the NoneBot APScheduler backend to the application lifecycle."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.runtime.plugins import (
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)

__plugin_meta__ = PluginMetadata(
    name="任务调度",
    description="绑定并管理应用的后台任务调度器。",
    usage="后台运行，无用户指令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)

if TYPE_CHECKING:
    from ironsbot.integrations.scheduler.facade import SchedulerFacade
    from ironsbot.runtime.matchers import MatcherRegistry


def _install(registry: MatcherRegistry, *, scheduler: SchedulerFacade) -> None:
    del registry
    from nonebot_plugin_apscheduler import scheduler as backend

    scheduler.bind(backend)


def plugin_contribution(*, scheduler: SchedulerFacade) -> PluginContribution:
    return PluginContribution(
        id="scheduler",
        install=partial(_install, scheduler=scheduler),
        hooks=PluginHooks(
            startup=(("scheduler", scheduler.start),),
            shutdown=(("scheduler", scheduler.shutdown),),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(scheduler=context.scheduler),
    )
