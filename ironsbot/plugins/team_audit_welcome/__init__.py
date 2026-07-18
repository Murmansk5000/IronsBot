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
from nonebot.rule import Rule

from ironsbot.services.team_audit_welcome import record_team_audit_pending_reminder
from ironsbot.shared.messaging.text import build_message, render_text

from .followup import (
    FIRST_FOLLOWUP_STEP,
    schedule_team_audit_followup,
)

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from ironsbot.config.models.message import TeamAuditWelcomeConfig
    from ironsbot.runtime.matchers import MatcherRegistry
    from ironsbot.shared.features import FeatureService
    from ironsbot.shared.messaging.senders import DeliveryResources


async def _is_group_increase(event: NoticeEvent) -> bool:
    return isinstance(event, GroupIncreaseNoticeEvent)


async def handle_team_audit_welcome(  # noqa: PLR0913
    bot: Bot,
    event: GroupIncreaseNoticeEvent,
    *,
    config: TeamAuditWelcomeConfig,
    scheduler: AsyncIOScheduler,
    features: FeatureService,
    delivery: DeliveryResources,
) -> None:
    should_send = (
        config.enabled
        and event.user_id != event.self_id
        and event.group_id in features.resolve_group_refs(config.groups)
        and features.is_group_feature_allowed(
            event.user_id,
            event.group_id,
            config.feature,
        )
    )
    if not should_send:
        return

    await bot.send_group_msg(
        group_id=event.group_id,
        message=build_message(
            render_text(config.message),
            at_user_ids=[event.user_id],
        ),
    )

    if not config.followup_enabled:
        return

    reminder = record_team_audit_pending_reminder(
        config.followup_cache_path,
        group_id=event.group_id,
        user_id=event.user_id,
        joined_at=datetime.now(timezone.utc),
        delay_hours=config.followup_after_hours,
        step=FIRST_FOLLOWUP_STEP,
    )
    schedule_team_audit_followup(
        scheduler,
        reminder,
        config=config,
        features=features,
        delivery=delivery,
    )


def install(
    registry: MatcherRegistry,
    config: TeamAuditWelcomeConfig,
    scheduler: AsyncIOScheduler,
    features: FeatureService,
    delivery: DeliveryResources,
) -> None:
    matcher = registry.on_notice(
        rule=Rule(_is_group_increase),
        priority=registry.priority("team_audit", 5),
        block=False,
    )
    matcher.append_handler(
        partial(
            handle_team_audit_welcome,
            config=config,
            scheduler=scheduler,
            features=features,
            delivery=delivery,
        )
    )
