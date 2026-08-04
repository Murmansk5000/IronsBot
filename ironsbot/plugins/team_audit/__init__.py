# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone
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
from ironsbot.runtime.matchers import bind_async
from ironsbot.runtime.plugins import (
    PluginContribution,
    PluginHooks,
    active_plugin_install_context,
)

if TYPE_CHECKING:
    from ironsbot.runtime.matchers import MatcherRegistry
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


async def handle_team_audit_welcome(
    bot: Bot,
    event: GroupIncreaseNoticeEvent,
    *,
    scheduler: Scheduler,
    service: TeamAuditService,
) -> None:
    if event.user_id == event.self_id:
        return
    await service.welcome(
        group_id=event.group_id,
        user_id=event.user_id,
        joined_at=datetime.now(timezone.utc),
        scheduler=scheduler,
        bot=bot,
    )


def install(
    registry: MatcherRegistry,
    scheduler: Scheduler,
    service: TeamAuditService,
) -> None:
    matcher = registry.on_notice(
        rule=Rule(_is_group_increase),
        priority=registry.priority("team_audit"),
        block=False,
    )
    matcher.append_handler(
        bind_async(
            handle_team_audit_welcome,
            scheduler=scheduler,
            service=service,
        )
    )


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
            bot_connect=(
                (
                    "team_audit_followups",
                    partial(service.start, scheduler=scheduler),
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
