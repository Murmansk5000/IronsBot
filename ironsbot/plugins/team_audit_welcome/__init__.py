# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot import on_notice
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    Message,
    NoticeEvent,
)
from nonebot.log import logger
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.config.loader import get_app_config
from ironsbot.services.team_audit_welcome import record_team_audit_pending_reminder
from ironsbot.shared.features import is_group_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging.outbound_rate_limit import (
    check_group_outbound_rate_limit,
)

from .followup import schedule_team_audit_followup
from .settings import (
    FIRST_FOLLOWUP_STEP,
    followup_cache_path,
    now_utc,
    target_groups,
    welcome_message,
)

__plugin_meta__ = PluginMetadata(
    name="战队审核入群提示",
    description="在指定战队审核群有新人入群时发送审核指引。",
    usage=(
        "配置 message.team_audit_welcome.enabled=true，并在 "
        "message.team_audit_welcome.groups 中填写群别名或群号。"
    ),
)


async def _is_group_increase(event: NoticeEvent) -> bool:
    return isinstance(event, GroupIncreaseNoticeEvent)


team_audit_welcome_matcher = on_notice(
    rule=Rule(_is_group_increase),
    priority=get_matcher_priority("team_audit", 5),
    block=False,
)


@team_audit_welcome_matcher.handle()
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

    rate_limit = check_group_outbound_rate_limit(event.group_id)
    if not rate_limit.allowed:
        return

    await bot.send_group_msg(
        group_id=event.group_id,
        message=welcome_message(event.user_id),
    )
    if rate_limit.cooldown_message is not None:
        await bot.send_group_msg(
            group_id=event.group_id,
            message=Message(rate_limit.cooldown_message),
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
