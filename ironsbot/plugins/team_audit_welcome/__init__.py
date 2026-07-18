# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    NoticeEvent,
)
from nonebot.log import logger
from nonebot.rule import Rule

from ironsbot.config.loader import get_app_config
from ironsbot.services.team_audit_welcome import record_team_audit_pending_reminder
from ironsbot.shared.features import is_group_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority

from .followup import schedule_team_audit_followup
from .settings import (
    FIRST_FOLLOWUP_STEP,
    followup_cache_path,
    now_utc,
    target_groups,
    welcome_message,
)

if TYPE_CHECKING:
    from ironsbot.runtime.matchers import MatcherRegistry


async def _is_group_increase(event: NoticeEvent) -> bool:
    return isinstance(event, GroupIncreaseNoticeEvent)


async def handle_team_audit_welcome(
    bot: Bot,
    event: GroupIncreaseNoticeEvent,
) -> None:
    config = get_app_config().message.team_audit_welcome
    should_send = (
        config.enabled
        and event.user_id != event.self_id
        and event.group_id in target_groups()
        and is_group_feature_allowed(event.user_id, event.group_id, config.feature)
    )
    if not should_send:
        return

    await bot.send_group_msg(
        group_id=event.group_id,
        message=welcome_message(event.user_id),
    )

    if not config.followup_enabled:
        return

    reminder = record_team_audit_pending_reminder(
        followup_cache_path(),
        group_id=event.group_id,
        user_id=event.user_id,
        joined_at=now_utc(),
        delay_hours=config.followup_after_hours,
        step=FIRST_FOLLOWUP_STEP,
    )

    try:
        from nonebot_plugin_apscheduler import scheduler
    except ImportError:
        logger.warning("team audit followup scheduler is unavailable")
        return

    schedule_team_audit_followup(scheduler, reminder)


def install(registry: MatcherRegistry) -> None:
    matcher = registry.on_notice(
        rule=Rule(_is_group_increase),
        priority=get_matcher_priority("team_audit", 5),
        block=False,
    )
    matcher.append_handler(handle_team_audit_welcome)
