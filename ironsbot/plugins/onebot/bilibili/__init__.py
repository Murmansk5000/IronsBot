# SPDX-License-Identifier: MIT
"""Bilibili command and monitor contributions for shared composition."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import HelpEntry, PluginContribution, PluginHooks
from ironsbot.services.bilibili.command_contracts import bilibili_command_contracts
from ironsbot.services.bilibili.runtime import BilibiliMonitorService

if TYPE_CHECKING:
    from ironsbot.core.platform import BotAccountRef
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.operations.scheduler import Scheduler


async def _check_on_connect(
    account: BotAccountRef, *, monitor: BilibiliMonitorService
) -> None:
    await monitor.check_on_connect(account.id)


def plugin_contribution(
    *, monitor: BilibiliMonitorService, scheduler: Scheduler
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
