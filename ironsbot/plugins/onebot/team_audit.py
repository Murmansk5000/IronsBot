# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.plugin import PluginMetadata

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)

if TYPE_CHECKING:
    from ironsbot.core.platform import BotAccountRef
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.team.audit import TeamAuditService

__plugin_meta__ = PluginMetadata(
    name="战队审核入群提示",
    description="在指定审核群中发送入群指引并安排后续提醒。",
    usage="后台 notice 插件，无用户指令。",
    type="application",
    homepage="https://github.com/Murmansk5000/IronsBot",
    supported_adapters={"~onebot.v11"},
)


async def restore_team_audit_followups(
    _account: BotAccountRef,
    *,
    scheduler: Scheduler,
    service: TeamAuditService,
) -> None:
    """Restore pending work when the OneBot connection becomes available."""

    await service.schedule_pending(scheduler)


def plugin_contribution(
    *,
    scheduler: Scheduler,
    service: TeamAuditService,
) -> PluginContribution:
    """Declare audit ownership and its follow-up lifecycle hooks."""

    return PluginContribution(
        id="team_audit",
        features=frozenset({Feature.TEAM_AUDIT}),
        hooks=PluginHooks(
            startup=(
                ("team_audit_followups", partial(service.start, scheduler=scheduler)),
            ),
            shutdown=(
                ("team_audit_followups", partial(service.stop, scheduler=scheduler)),
            ),
            bot_connect=(
                (
                    "team_audit_recovery",
                    partial(
                        restore_team_audit_followups,
                        scheduler=scheduler,
                        service=service,
                    ),
                ),
            ),
        ),
    )


if (context := active_plugin_install_context()) is not None:
    context.contribute(
        __plugin_meta__,
        plugin_contribution(
            scheduler=context.scheduler,
            service=context.resources.team_audit,
        ),
    )
