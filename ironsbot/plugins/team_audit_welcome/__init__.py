# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from nonebot import on_notice
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    Message,
    NoticeEvent,
)
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.log import logger
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.config.loader import get_app_config
from ironsbot.services.team_audit_welcome import (
    TeamAuditPendingReminder,
    clear_team_audit_pending_reminder,
    get_team_audit_pending_reminder,
    list_team_audit_pending_reminders,
    record_team_audit_pending_reminder,
)
from ironsbot.shared.features import is_group_feature_allowed, resolve_group_refs
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging.outbound_rate_limit import (
    check_group_outbound_rate_limit,
)
from ironsbot.shared.messaging.text import build_message, render_text
from ironsbot.shared.scheduler import JobRegistry

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

TEAM_AUDIT_WELCOME_PLUGIN_NAME = "team_audit_welcome"
TEAM_AUDIT_FOLLOWUP_JOB_PREFIX = "team_audit_followup_"
FOLLOWUP_SCAN_INTERVAL_MINUTES = 10
FIRST_FOLLOWUP_STEP = 1
FINAL_FOLLOWUP_STEP = 2

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


def _target_groups() -> set[int]:
    config = get_app_config().message.team_audit_welcome
    return set(resolve_group_refs(config.groups))


def _welcome_message(user_id: int) -> Message:
    config = get_app_config().message.team_audit_welcome
    return build_message(render_text(config.message), at_user_ids=[user_id])


def _followup_message(
    user_id: int,
    *,
    group_id: int,
    reminder: TeamAuditPendingReminder,
) -> Message:
    config = get_app_config().message.team_audit_welcome
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


def _followup_cache_path() -> str:
    return get_app_config().message.team_audit_welcome.followup_cache_path


def _followup_job_id(group_id: int, user_id: int) -> str:
    return f"{TEAM_AUDIT_FOLLOWUP_JOB_PREFIX}{_followup_job_suffix(group_id, user_id)}"


def _followup_job_suffix(group_id: int, user_id: int) -> str:
    return f"{group_id}_{user_id}"


def _followup_scan_job_id(bot: Bot) -> str:
    return f"{TEAM_AUDIT_FOLLOWUP_JOB_PREFIX}{_followup_scan_job_suffix(bot)}"


def _followup_scan_job_suffix(bot: Bot) -> str:
    return f"scan_{bot.self_id}"


def _followup_job_registry(scheduler: "AsyncIOScheduler") -> JobRegistry:
    return JobRegistry(scheduler, prefix=TEAM_AUDIT_FOLLOWUP_JOB_PREFIX)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
    scheduler: "AsyncIOScheduler",
    bot: Bot,
    reminder: TeamAuditPendingReminder,
    *,
    now: datetime | None = None,
) -> None:
    config = get_app_config().message.team_audit_welcome
    if not config.enabled or not config.followup_enabled:
        return

    now = now or _now_utc()
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
    scheduler: "AsyncIOScheduler",
) -> None:
    config = get_app_config().message.team_audit_welcome
    if not config.enabled or not config.followup_enabled:
        return

    for reminder in list_team_audit_pending_reminders(_followup_cache_path()):
        schedule_team_audit_followup(scheduler, bot, reminder)


def register_team_audit_followup_scan(
    scheduler: "AsyncIOScheduler",
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
        _followup_cache_path(),
        group_id=group_id,
        user_id=user_id,
    )


def _load_pending_reminder(
    *,
    group_id: int,
    user_id: int,
) -> TeamAuditPendingReminder | None:
    return get_team_audit_pending_reminder(
        _followup_cache_path(),
        group_id=group_id,
        user_id=user_id,
    )


def _schedule_final_followup(
    bot: Bot,
    reminder: TeamAuditPendingReminder,
) -> None:
    config = get_app_config().message.team_audit_welcome
    final_reminder = record_team_audit_pending_reminder(
        _followup_cache_path(),
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

    if group_id not in _target_groups():
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
        message=_followup_message(user_id, group_id=group_id, reminder=reminder),
    )
    if rate_limit.cooldown_message is not None:
        await bot.send_group_msg(
            group_id=group_id,
            message=Message(rate_limit.cooldown_message),
        )

    _finish_sent_followup(bot, reminder)


@team_audit_welcome_matcher.handle()
async def handle_team_audit_welcome(
    bot: Bot,
    event: GroupIncreaseNoticeEvent,
) -> None:
    config = get_app_config().message.team_audit_welcome
    should_send = (
        config.enabled
        and event.user_id != event.self_id
        and event.group_id in _target_groups()
        and is_group_feature_allowed(event.user_id, event.group_id, config.feature)
    )
    if not should_send:
        return

    rate_limit = check_group_outbound_rate_limit(event.group_id)
    if not rate_limit.allowed:
        return

    await bot.send_group_msg(
        group_id=event.group_id,
        message=_welcome_message(event.user_id),
    )
    if rate_limit.cooldown_message is not None:
        await bot.send_group_msg(
            group_id=event.group_id,
            message=Message(rate_limit.cooldown_message),
        )

    if not config.followup_enabled:
        return

    reminder = record_team_audit_pending_reminder(
        _followup_cache_path(),
        group_id=event.group_id,
        user_id=event.user_id,
        joined_at=_now_utc(),
        delay_hours=config.followup_after_hours,
        step=FIRST_FOLLOWUP_STEP,
    )

    try:
        from nonebot_plugin_apscheduler import scheduler
    except ImportError:
        logger.warning("team audit followup scheduler is unavailable")
        return

    schedule_team_audit_followup(scheduler, bot, reminder)
