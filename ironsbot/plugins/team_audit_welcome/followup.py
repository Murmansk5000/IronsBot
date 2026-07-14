# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import Bot, Message
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.log import logger

from ironsbot.config.loader import get_app_config
from ironsbot.services.team_audit_welcome import (
    TeamAuditPendingReminder,
    clear_team_audit_pending_reminder,
    get_team_audit_pending_reminder,
    list_team_audit_pending_reminders,
    record_team_audit_pending_reminder,
)
from ironsbot.shared.features import is_group_feature_allowed
from ironsbot.shared.messaging.outbound_rate_limit import (
    check_group_outbound_rate_limit,
)
from ironsbot.shared.runtime.jobs import JobRegistry

from .settings import (
    FINAL_FOLLOWUP_STEP,
    FOLLOWUP_SCAN_INTERVAL_MINUTES,
    TEAM_AUDIT_FOLLOWUP_JOB_PREFIX,
    followup_cache_path,
    followup_message,
    now_utc,
    target_groups,
)

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


def _followup_job_suffix(group_id: int, user_id: int) -> str:
    return f"{group_id}_{user_id}"


def _followup_scan_job_suffix(bot: Bot) -> str:
    return f"scan_{bot.self_id}"


def _followup_job_registry(scheduler: AsyncIOScheduler) -> JobRegistry:
    return JobRegistry(scheduler, prefix=TEAM_AUDIT_FOLLOWUP_JOB_PREFIX)


async def _is_member_still_in_group(
    bot: Bot,
    *,
    group_id: int,
    user_id: int,
) -> bool:
    try:
        await bot.get_group_member_info(
            group_id=group_id,
            user_id=user_id,
            no_cache=True,
        )
    except ActionFailed:
        return False
    return True


def schedule_team_audit_followup(
    scheduler: AsyncIOScheduler,
    bot: Bot,
    reminder: TeamAuditPendingReminder,
    *,
    now: datetime | None = None,
) -> None:
    config = get_app_config().message.team_audit_welcome
    if not config.enabled or not config.followup_enabled:
        return

    now = now or now_utc()
    run_at = reminder.remind_at
    if run_at <= now:
        run_at = now + timedelta(seconds=1)

    _followup_job_registry(scheduler).add(
        send_team_audit_followup,
        "date",
        run_date=run_at,
        args=[bot, reminder.group_id, reminder.user_id],
        job_id=_followup_job_suffix(reminder.group_id, reminder.user_id),
        misfire_grace_time=3600,
    )


async def schedule_pending_team_audit_followups(
    bot: Bot,
    scheduler: AsyncIOScheduler,
) -> None:
    config = get_app_config().message.team_audit_welcome
    if not config.enabled or not config.followup_enabled:
        return

    for reminder in list_team_audit_pending_reminders(followup_cache_path()):
        schedule_team_audit_followup(scheduler, bot, reminder)


def register_team_audit_followup_scan(
    scheduler: AsyncIOScheduler,
    bot: Bot,
) -> None:
    _followup_job_registry(scheduler).add(
        schedule_pending_team_audit_followups,
        "interval",
        minutes=FOLLOWUP_SCAN_INTERVAL_MINUTES,
        args=[bot, scheduler],
        job_id=_followup_scan_job_suffix(bot),
    )


def _clear_pending_reminder(*, group_id: int, user_id: int) -> None:
    clear_team_audit_pending_reminder(
        followup_cache_path(),
        group_id=group_id,
        user_id=user_id,
    )


def _load_pending_reminder(
    *,
    group_id: int,
    user_id: int,
) -> TeamAuditPendingReminder | None:
    return get_team_audit_pending_reminder(
        followup_cache_path(),
        group_id=group_id,
        user_id=user_id,
    )


def _schedule_final_followup(
    bot: Bot,
    reminder: TeamAuditPendingReminder,
) -> None:
    config = get_app_config().message.team_audit_welcome
    final_reminder = record_team_audit_pending_reminder(
        followup_cache_path(),
        group_id=reminder.group_id,
        user_id=reminder.user_id,
        joined_at=reminder.joined_at,
        delay_hours=config.final_followup_after_hours,
        step=FINAL_FOLLOWUP_STEP,
    )
    try:
        from nonebot_plugin_apscheduler import scheduler
    except ImportError:
        logger.warning("team audit final followup scheduler is unavailable")
        return

    schedule_team_audit_followup(scheduler, bot, final_reminder)


def _finish_sent_followup(
    bot: Bot,
    reminder: TeamAuditPendingReminder,
) -> None:
    config = get_app_config().message.team_audit_welcome
    if reminder.step < FINAL_FOLLOWUP_STEP and config.final_followup_enabled:
        _schedule_final_followup(bot, reminder)
        return
    _clear_pending_reminder(group_id=reminder.group_id, user_id=reminder.user_id)


async def send_team_audit_followup(  # noqa: PLR0911
    bot: Bot,
    group_id: int,
    user_id: int,
) -> None:
    config = get_app_config().message.team_audit_welcome
    if not config.enabled or not config.followup_enabled:
        return

    reminder = _load_pending_reminder(group_id=group_id, user_id=user_id)
    if reminder is None:
        return
    if reminder.step >= FINAL_FOLLOWUP_STEP and not config.final_followup_enabled:
        _clear_pending_reminder(group_id=group_id, user_id=user_id)
        return

    if group_id not in target_groups():
        _clear_pending_reminder(group_id=group_id, user_id=user_id)
        return

    if not is_group_feature_allowed(user_id, group_id, config.feature):
        return

    if not await _is_member_still_in_group(bot, group_id=group_id, user_id=user_id):
        _clear_pending_reminder(group_id=group_id, user_id=user_id)
        return

    rate_limit = check_group_outbound_rate_limit(group_id)
    if not rate_limit.allowed:
        logger.info(
            "team audit followup skipped by outbound rate limit: "
            f"group={group_id} user={user_id}"
        )
        return

    await bot.send_group_msg(
        group_id=group_id,
        message=followup_message(user_id, group_id=group_id, reminder=reminder),
    )
    if rate_limit.cooldown_message is not None:
        await bot.send_group_msg(
            group_id=group_id,
            message=Message(rate_limit.cooldown_message),
        )

    _finish_sent_followup(bot, reminder)


__all__ = [
    "FOLLOWUP_SCAN_INTERVAL_MINUTES",
    "register_team_audit_followup_scan",
    "schedule_pending_team_audit_followups",
    "schedule_team_audit_followup",
    "send_team_audit_followup",
]
