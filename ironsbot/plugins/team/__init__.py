# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupIncreaseNoticeEvent, NoticeEvent
from nonebot.rule import Rule

from ironsbot.runtime.matchers import bind_async

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.runtime.matchers import MatcherRegistry
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.team.audit import TeamAuditService


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
