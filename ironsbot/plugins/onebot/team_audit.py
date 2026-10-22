# SPDX-License-Identifier: MIT
from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    NoticeEvent,
)
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.core.features import Feature
from ironsbot.core.plugin_install import (
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)
from ironsbot.integrations.onebot.notice_events import welcome_onebot_member

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.matchers import MatcherFactory
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


def _is_group_increase(event: NoticeEvent) -> bool:
    return isinstance(event, GroupIncreaseNoticeEvent)


async def restore_team_audit_followups(
    _bot: Bot,
    *,
    scheduler: Scheduler,
    service: TeamAuditService,
) -> None:
    """Restore pending work when the OneBot connection becomes available."""

    await service.schedule_pending(scheduler)


def install(
    registry: MatcherFactory,
    scheduler: Scheduler,
    service: TeamAuditService,
) -> None:
    async def handle(event: GroupIncreaseNoticeEvent) -> None:
        await welcome_onebot_member(
            event.self_id,
            event.user_id,
            event.group_id,
            scheduler=scheduler,
            service=service,
        )

    matcher = registry.on_notice(
        rule=Rule(_is_group_increase),
        priority=registry.priority("team_audit"),
        block=False,
    )
    matcher.append_handler(handle)


def plugin_contribution(
    *,
    scheduler: Scheduler,
    service: TeamAuditService,
) -> PluginContribution:
    """Declare the audit notice matcher and its follow-up scheduler hook."""

    return PluginContribution(
        id="team_audit",
        features=frozenset({Feature.TEAM_AUDIT}),
        install=partial(install, scheduler=scheduler, service=service),
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
