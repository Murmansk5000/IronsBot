# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.log import logger

from ironsbot.integrations.scheduler.jobs import JobRegistry
from ironsbot.services.team_audit_welcome import (
    TeamAuditPendingReminder,
    clear_team_audit_pending_reminder,
    get_team_audit_pending_reminder,
    list_team_audit_pending_reminders,
    record_team_audit_pending_reminder,
)
from ironsbot.shared.features import is_group_feature_allowed, resolve_group_refs
from ironsbot.shared.messaging import (
    MessageTarget,
    get_bot_for_group,
    send_target_messages,
)
from ironsbot.shared.messaging.text import build_message, render_text

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from nonebot.adapters.onebot.v11 import Bot, Message

    from ironsbot.config.models.message import TeamAuditWelcomeConfig

TEAM_AUDIT_FOLLOWUP_JOB_PREFIX = "team_audit_followup_"
FOLLOWUP_SCAN_INTERVAL_MINUTES = 10
FIRST_FOLLOWUP_STEP = 1
FINAL_FOLLOWUP_STEP = 2


def _followup_job_suffix(group_id: int, user_id: int) -> str:
    return f"{group_id}_{user_id}"


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


async def _bot_can_access_group(bot: Bot, *, group_id: int) -> bool:
    try:
        await bot.get_group_info(group_id=group_id, no_cache=True)
    except ActionFailed as e:
        logger.warning(
            "team audit followup bot cannot access target group: "
            f"group={group_id} bot_self_id={bot.self_id} error={e}"
        )
        return False
    return True


def _followup_message(
    config: TeamAuditWelcomeConfig,
    user_id: int,
    *,
    group_id: int,
    reminder: TeamAuditPendingReminder,
) -> Message:
    is_final = reminder.step >= FINAL_FOLLOWUP_STEP
    template = render_text(
        config.final_followup_message if is_final else config.followup_message
    )
    hours = (
        config.final_followup_after_hours if is_final else config.followup_after_hours
    )
    try:
        text = template.format(
            hours=hours,
            group_id=group_id,
            user_id=user_id,
        )
    except (IndexError, KeyError, ValueError):
        text = template
    return build_message(text, at_user_ids=[user_id])


def schedule_team_audit_followup(
    scheduler: AsyncIOScheduler,
    reminder: TeamAuditPendingReminder,
    *,
    config: TeamAuditWelcomeConfig,
    now: datetime | None = None,
) -> None:
    if not config.enabled or not config.followup_enabled:
        return

    now = now or datetime.now(timezone.utc)
    run_at = reminder.remind_at
    if run_at <= now:
        run_at = now + timedelta(seconds=1)

    _followup_job_registry(scheduler).add(
        send_team_audit_followup,
        "date",
        run_date=run_at,
        args=[reminder.group_id, reminder.user_id],
        kwargs={"config": config, "scheduler": scheduler},
        job_id=_followup_job_suffix(reminder.group_id, reminder.user_id),
        misfire_grace_time=3600,
    )


async def schedule_pending_team_audit_followups(
    scheduler: AsyncIOScheduler,
    *,
    config: TeamAuditWelcomeConfig,
) -> None:
    if not config.enabled or not config.followup_enabled:
        return

    for reminder in list_team_audit_pending_reminders(config.followup_cache_path):
        schedule_team_audit_followup(scheduler, reminder, config=config)


def register_team_audit_followup_scan(
    scheduler: AsyncIOScheduler,
    *,
    config: TeamAuditWelcomeConfig,
) -> None:
    _followup_job_registry(scheduler).add(
        schedule_pending_team_audit_followups,
        "interval",
        minutes=FOLLOWUP_SCAN_INTERVAL_MINUTES,
        args=[scheduler],
        kwargs={"config": config},
        job_id="scan",
    )


def _schedule_final_followup(
    reminder: TeamAuditPendingReminder,
    *,
    config: TeamAuditWelcomeConfig,
    scheduler: AsyncIOScheduler,
) -> None:
    final_reminder = record_team_audit_pending_reminder(
        config.followup_cache_path,
        group_id=reminder.group_id,
        user_id=reminder.user_id,
        joined_at=reminder.joined_at,
        delay_hours=config.final_followup_after_hours,
        step=FINAL_FOLLOWUP_STEP,
    )
    schedule_team_audit_followup(scheduler, final_reminder, config=config)


def _finish_sent_followup(
    reminder: TeamAuditPendingReminder,
    *,
    config: TeamAuditWelcomeConfig,
    scheduler: AsyncIOScheduler,
) -> None:
    if reminder.step < FINAL_FOLLOWUP_STEP and config.final_followup_enabled:
        _schedule_final_followup(
            reminder,
            config=config,
            scheduler=scheduler,
        )
        return
    clear_team_audit_pending_reminder(
        config.followup_cache_path,
        group_id=reminder.group_id,
        user_id=reminder.user_id,
    )


async def send_team_audit_followup(  # noqa: PLR0911
    group_id: int,
    user_id: int,
    *,
    config: TeamAuditWelcomeConfig,
    scheduler: AsyncIOScheduler,
) -> None:
    if not config.enabled or not config.followup_enabled:
        return

    reminder = get_team_audit_pending_reminder(
        config.followup_cache_path,
        group_id=group_id,
        user_id=user_id,
    )
    if reminder is None:
        return
    if reminder.step >= FINAL_FOLLOWUP_STEP and not config.final_followup_enabled:
        clear_team_audit_pending_reminder(
            config.followup_cache_path,
            group_id=group_id,
            user_id=user_id,
        )
        return

    if group_id not in resolve_group_refs(config.groups):
        clear_team_audit_pending_reminder(
            config.followup_cache_path,
            group_id=group_id,
            user_id=user_id,
        )
        return

    if not is_group_feature_allowed(user_id, group_id, config.feature):
        return

    bot = get_bot_for_group(group_id)
    if bot is None:
        logger.warning(
            "team audit followup skipped: no connected bot for "
            f"group={group_id} user={user_id}"
        )
        return

    if not await _bot_can_access_group(bot, group_id=group_id):
        return

    if not await _is_member_still_in_group(bot, group_id=group_id, user_id=user_id):
        clear_team_audit_pending_reminder(
            config.followup_cache_path,
            group_id=group_id,
            user_id=user_id,
        )
        return

    summary = await send_target_messages(
        [MessageTarget("group", group_id)],
        _followup_message(config, user_id, group_id=group_id, reminder=reminder),
        bot=bot,
        action_name="team audit followup",
        interval_seconds=0,
    )
    if not summary.succeeded:
        logger.warning(
            "team audit followup send failed: group={} user={} bot_self_id={}",
            group_id,
            user_id,
            bot.self_id,
        )
        return

    _finish_sent_followup(
        reminder,
        config=config,
        scheduler=scheduler,
    )


__all__ = [
    "FOLLOWUP_SCAN_INTERVAL_MINUTES",
    "register_team_audit_followup_scan",
    "schedule_pending_team_audit_followups",
    "schedule_team_audit_followup",
    "send_team_audit_followup",
]
