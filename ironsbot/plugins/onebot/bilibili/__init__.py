# SPDX-License-Identifier: MIT
"""OneBot Bilibili command, monitor, and manifest integration."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    HelpEntry,
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.services.bilibili.command_contracts import bilibili_command_contracts
from ironsbot.services.bilibili.runtime import BilibiliMonitorService

from .commands import install

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.portable_query_sessions import PortableQuerySessions

__plugin_meta__ = PluginMetadata(
    name="B站动态",
    description="查询、刷新和自动推送已订阅 UID 的 Bilibili 动态。",
    usage="发送“动态”查询已订阅账号的动态。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


async def _check_on_connect(bot: Bot, *, monitor: BilibiliMonitorService) -> None:
    await monitor.check_on_connect(str(bot.self_id))


def plugin_contribution(
    *,
    service: BilibiliService,
    features: FeatureService,
    monitor: BilibiliMonitorService,
    scheduler: Scheduler,
    query_sessions: PortableQuerySessions,
) -> PluginContribution:
    """Declare Bilibili commands, delivery construction, and monitor lifecycle."""

    return PluginContribution(
        id="bilibili",
        features=frozenset({Feature.BILI_QUERY, Feature.BILI_PUSH}),
        help=HelpEntry(
            name="B站动态",
            description="查询、刷新和自动推送已订阅 UID 的 Bilibili 动态",
            group="message",
            order=20,
        ),
        commands=bilibili_command_contracts(),
        install=partial(
            install,
            service=service,
            features=features,
            monitor=monitor,
            targets=service.targets,
            query_sessions=query_sessions,
        ),
        hooks=PluginHooks(
            startup=(
                (
                    "bilibili_monitor_jobs",
                    partial(monitor.register_job, scheduler),
                ),
            ),
            first_bot_connect=(
                (
                    "bilibili_check",
                    partial(_check_on_connect, monitor=monitor),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            service=context.resources.bilibili,
            features=context.resources.features,
            monitor=context.resources.bilibili_monitor,
            scheduler=context.scheduler,
            query_sessions=context.resources.query_sessions,
        ),
    )
