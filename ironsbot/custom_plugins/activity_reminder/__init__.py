# SPDX-License-Identifier: MIT
import asyncio
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from nonebot import get_driver, on_message, require
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.services.activity.catalog import build_active_activity_infos
from ironsbot.services.activity.commands import (
    is_current_activity_query_text,
    is_soon_ending_activity_query_text,
)
from ironsbot.services.activity.delivery import (
    filter_reminders_before_send,
    format_reminder_message,
)
from ironsbot.services.activity.formatting import (
    format_activity_line,
)
from ironsbot.services.activity.models import (
    ActivityDeadline,
    ActivityInfo,
    ActivityInfoCache,
    ActivityReminder,
)
from ironsbot.services.activity.planning import (
    activity_deadline,
    activity_is_soon_ending,
    activity_sort_end_time,
    build_scheduled_reminders,
    group_by_send_time,
)
from ironsbot.services.activity.repository import load_activity_rows
from ironsbot.services.activity.sent_cache import filter_unsent, mark_sent
from ironsbot.shared.features import (
    groups_for_feature,
    is_event_feature_allowed,
    users_for_feature,
    users_with_superusers,
)
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .config import Config, get_activity_config

require("ironsbot.plugins.seer_data")

from ironsbot.plugins.db_sync.manager import db_manager

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SEERAPI_DB_NAME = "seerapi"
ACTIVITY_REMINDER_PLUGIN_NAME = "activity_reminder"
DEFAULT_MESSAGE_TEMPLATE = "⏰ 本周活动将在约 {lead_hours} 小时后结束\n{activity_list}"
SOON_ENDING_THRESHOLD = timedelta(days=7)
REMINDER_SEND_DELAY = timedelta(minutes=10)
REMINDER_DISPATCH_TOLERANCE = timedelta(minutes=1)
ACTIVITY_INFO_CACHE_TTL = timedelta(seconds=60)
SECONDS_PER_MINUTE = 60


async def _is_current_activity_query_command(event: Event) -> bool:
    return is_current_activity_query_text(event.get_plaintext())


async def _is_soon_ending_activity_query_command(event: Event) -> bool:
    return is_soon_ending_activity_query_text(event.get_plaintext())


__plugin_meta__ = PluginMetadata(
    name="活动结束提醒",
    description="从 SeerAPI 活动数据读取结束时间，提前提醒活动即将结束",
    usage=(
        "【活动结束提醒】\n"
        "按 activity.lead_hours 配置提前提醒活动即将结束。\n"
        "Target groups use FEATURE_GROUP_POLICY feature: activity_push.\n"
        "Target users use FEATURE_USER_POLICY feature: activity_push.\n"
        "超级管理员可发 /当前活动、活动列表、活动时间 查看当前活动和剩余时间；"
        "发送 快结束活动 查看不足 7 天结束的活动。"
    ),
    config=Config,
)


_activity_info_cache = ActivityInfoCache()
_activity_reminder_runtime_state: dict[str, Any] = {
    "registered": False,
    "scheduler": None,
}


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _activity_deadline(
    activity: ActivityInfo,
    now: datetime,
) -> ActivityDeadline | None:
    return activity_deadline(
        activity,
        now,
        soon_ending_threshold=SOON_ENDING_THRESHOLD,
    )


def _activity_is_soon_ending(activity: ActivityInfo, now: datetime) -> bool:
    return activity_is_soon_ending(
        activity,
        now,
        soon_ending_threshold=SOON_ENDING_THRESHOLD,
    )


def _activity_sort_end_time(
    activity: ActivityInfo,
    now: datetime | None = None,
) -> datetime:
    return activity_sort_end_time(
        activity,
        now,
        soon_ending_threshold=SOON_ENDING_THRESHOLD if now is not None else None,
    )


def _load_activity_rows() -> list[Mapping[str, Any]]:
    return load_activity_rows(
        db_manager.get_session,
        database_name=SEERAPI_DB_NAME,
        only_shown=get_activity_config().only_shown,
    )


def _active_activity_infos(now: datetime) -> list[ActivityInfo]:
    if (
        _activity_info_cache.expires_at is not None
        and _activity_info_cache.expires_at > now
    ):
        return [
            activity
            for activity in _activity_info_cache.items
            if activity.end_time > now
            and (
                activity.start_time is None
                or activity.start_time <= now
            )
        ]

    sorted_activities = build_active_activity_infos(_load_activity_rows(), now)
    _activity_info_cache.items = sorted_activities
    _activity_info_cache.expires_at = now + ACTIVITY_INFO_CACHE_TTL
    return list(sorted_activities)


def _soon_ending_activity_infos(now: datetime) -> list[ActivityInfo]:
    activities = [
        activity
        for activity in _active_activity_infos(now)
        if _activity_is_soon_ending(activity, now)
    ]
    return sorted(
        activities,
        key=lambda activity: (
            _activity_sort_end_time(activity, now),
            activity.sort_order,
            activity.activity_id,
        ),
    )


def build_current_activity_message(
    now: datetime | None = None,
    *,
    limit: int | None = None,
    soon_only: bool = False,
) -> str:
    current_time = now or _now()
    activities = (
        _soon_ending_activity_infos(current_time)
        if soon_only
        else _active_activity_infos(current_time)
    )

    if not activities:
        if soon_only:
            return "📭 当前没有读到不足 7 天结束的活动。"
        return "📭 当前没有从活动中心读到正在进行的活动。"

    shown_activities = activities if limit is None else activities[:limit]
    title = "快结束活动" if soon_only else "当前活动"
    lines = [
        f"📅【{title}】",
        f"截至 {current_time:%Y-%m-%d %H:%M}",
        "",
    ]

    for index, activity in enumerate(shown_activities, start=1):
        lines.extend(
            format_activity_line(
                index,
                activity,
                current_time,
                soon_only=soon_only,
                deadline=(
                    _activity_deadline(activity, current_time)
                    if soon_only
                    else None
                ),
            )
        )

    hidden_count = len(activities) - len(shown_activities)
    if limit is not None and hidden_count > 0:
        lines.append(f"...还有 {hidden_count} 个活动未显示")
    return "\n".join(lines)


def _build_scheduled_reminders(now: datetime) -> list[ActivityReminder]:
    return build_scheduled_reminders(
        _soon_ending_activity_infos(now),
        now,
        lead_hours=get_activity_config().lead_hours,
        reminder_send_delay=REMINDER_SEND_DELAY,
        grace=timedelta(minutes=get_activity_config().grace_minutes),
        soon_ending_threshold=SOON_ENDING_THRESHOLD,
    )


def _format_message(lead_hours: int, reminders: list[ActivityReminder]) -> str:
    return format_reminder_message(
        lead_hours,
        reminders,
        template=get_activity_config().message,
        fallback_template=DEFAULT_MESSAGE_TEMPLATE,
    )


def _group_by_send_time(
    reminders: Iterable[ActivityReminder],
) -> dict[tuple[int, datetime], list[ActivityReminder]]:
    return group_by_send_time(reminders)


def _filter_valid_reminders_before_send(
    reminders: Iterable[ActivityReminder],
    *,
    now: datetime,
) -> list[ActivityReminder]:
    return filter_reminders_before_send(
        reminders,
        now=now,
        current_activities=_soon_ending_activity_infos(now),
        dispatch_tolerance=REMINDER_DISPATCH_TOLERANCE,
        soon_ending_threshold=SOON_ENDING_THRESHOLD,
    )


async def send_activity_reminder(
    *,
    lead_hours: int,
    reminders: list[ActivityReminder],
) -> None:
    from ironsbot.custom_plugins.message_actions import send_broadcast_message

    reminders = _filter_valid_reminders_before_send(reminders, now=_now())
    if not reminders:
        logger.info(
            f"activity ending reminder {lead_hours}h skipped: no valid reminders"
        )
        return

    target_groups = groups_for_feature("activity_push")
    target_users = users_with_superusers(users_for_feature("activity_push"))
    if not target_groups and not target_users:
        logger.warning("activity reminder skipped: no target groups or users")
        return

    message = _format_message(lead_hours, reminders)
    summary = await send_broadcast_message(
        message,
        group_ids=target_groups,
        private_user_ids=target_users,
        action_name=f"activity ending reminder {lead_hours}h",
        interval_seconds=1.2,
    )
    if summary.succeeded:
        mark_sent(reminders)


def _reminder_job_id(lead_hours: int, send_time: datetime) -> str:
    return f"activity_reminder_{lead_hours}h_{int(send_time.timestamp())}"


async def schedule_activity_reminders() -> None:
    scheduler = _activity_reminder_runtime_state["scheduler"]
    if scheduler is None:
        logger.warning("activity reminder scheduler is not configured")
        return

    config = get_activity_config()
    if not config.enabled:
        return

    try:
        reminders = filter_unsent(_build_scheduled_reminders(_now()))
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("activity reminder scan failed")
        return

    if not reminders:
        logger.info("activity reminder scan found no pending reminders")
        return

    scheduled_count = 0
    for (lead_hours, send_time), lead_reminders in _group_by_send_time(
        reminders
    ).items():
        scheduler.add_job(
            send_activity_reminder,
            "date",
            kwargs={
                "lead_hours": lead_hours,
                "reminders": lead_reminders,
            },
            id=_reminder_job_id(lead_hours, send_time),
            replace_existing=True,
            run_date=send_time,
            misfire_grace_time=(
                config.grace_minutes * SECONDS_PER_MINUTE
            ),
        )
        scheduled_count += len(lead_reminders)

    logger.info(f"activity reminder scheduled {scheduled_count} pending reminders")


current_activity_matcher = on_message(
    rule=Rule(_is_current_activity_query_command) & no_reply(),
    permission=SUPERUSER,
    priority=5,
    block=True,
)

soon_ending_activity_matcher = on_message(
    rule=(
        Rule(lambda event: is_event_feature_allowed(event, "activity_query"))
        & Rule(_is_soon_ending_activity_query_command)
        & no_reply()
    ),
    priority=5,
    block=True,
)


class ActivityReminderPlugin:
    name = ACTIVITY_REMINDER_PLUGIN_NAME
    feature = "activity_query"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        from ironsbot.custom_plugins.message_actions import finish_event_reply

        matcher = context.matcher or soon_ending_activity_matcher
        if context.action == "current":
            await finish_event_reply(
                matcher,
                event,
                await asyncio.to_thread(build_current_activity_message),
            )
            return

        if context.action == "soon_ending":
            await finish_event_reply(
                matcher,
                event,
                await asyncio.to_thread(build_current_activity_message, soon_only=True),
            )


register_plugin(ActivityReminderPlugin())


@current_activity_matcher.handle()
async def handle_current_activity_query(
    event: MessageEvent,
) -> None:
    await dispatch_plugin(
        plugin_name=ACTIVITY_REMINDER_PLUGIN_NAME,
        event=event,
        matcher=current_activity_matcher,
        action="current",
    )


@soon_ending_activity_matcher.handle()
async def handle_soon_ending_activity_query(event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=ACTIVITY_REMINDER_PLUGIN_NAME,
        event=event,
        matcher=soon_ending_activity_matcher,
        action="soon_ending",
    )


def register_activity_reminder_jobs(scheduler: Any) -> None:
    if not get_activity_config().enabled:
        return

    scheduler.add_job(
        schedule_activity_reminders,
        "date",
        id="activity_reminder_startup_scan",
        replace_existing=True,
        next_run_time=_now() + timedelta(seconds=30),
        misfire_grace_time=300,
    )
    scheduler.add_job(
        schedule_activity_reminders,
        "cron",
        id="activity_reminder_daily_scan",
        replace_existing=True,
        hour=0,
        minute=0,
        second=0,
        misfire_grace_time=300,
    )


def _setup_activity_reminder_runtime(driver: Any, scheduler: Any) -> None:
    if _activity_reminder_runtime_state["registered"]:
        return

    _activity_reminder_runtime_state["scheduler"] = scheduler

    @driver.on_startup
    async def _register_activity_reminder_jobs_on_startup() -> None:
        register_activity_reminder_jobs(scheduler)

    _activity_reminder_runtime_state["registered"] = True


def setup_activity_reminder_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_activity_reminder_runtime(get_driver(), scheduler)
