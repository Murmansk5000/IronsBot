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

from ironsbot.services.activity.commands import (
    is_current_activity_query_text,
    is_soon_ending_activity_query_text,
)
from ironsbot.services.activity.delivery import (
    filter_reminders_before_send,
    format_reminder_message,
)
from ironsbot.services.activity.models import (
    ActivityInfo,
    ActivityInfoCache,
    ActivityReminder,
)
from ironsbot.services.activity.planning import (
    build_scheduled_reminders,
)
from ironsbot.services.activity.query import (
    ActivityQuerySource,
    active_activity_infos,
    build_activity_query_message,
    soon_ending_activity_infos,
)
from ironsbot.services.activity.repository import load_activity_rows
from ironsbot.services.activity.scheduler import (
    register_scan_jobs,
    schedule_reminder_jobs,
)
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

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SEERAPI_DB_NAME = "seerapi"
ACTIVITY_REMINDER_PLUGIN_NAME = "activity_reminder"
DEFAULT_MESSAGE_TEMPLATE = "⏰ 本周活动将在约 {lead_hours} 小时后结束\n{activity_list}"
SOON_ENDING_THRESHOLD = timedelta(days=7)
REMINDER_SEND_DELAY = timedelta(minutes=10)
REMINDER_DISPATCH_TOLERANCE = timedelta(minutes=1)
ACTIVITY_INFO_CACHE_TTL = timedelta(seconds=60)


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


def _activity_db_session_factory() -> Any:
    require("ironsbot.plugins.seer_data")
    from ironsbot.plugins.db_sync.manager import db_manager

    return db_manager.get_session


def _load_activity_rows() -> list[Mapping[str, Any]]:
    return load_activity_rows(
        _activity_db_session_factory(),
        database_name=SEERAPI_DB_NAME,
        only_shown=get_activity_config().only_shown,
    )


_activity_query_source = ActivityQuerySource(
    cache=_activity_info_cache,
    load_rows=_load_activity_rows,
    cache_ttl=ACTIVITY_INFO_CACHE_TTL,
    soon_ending_threshold=SOON_ENDING_THRESHOLD,
)


def _active_activity_infos(now: datetime) -> list[ActivityInfo]:
    return active_activity_infos(
        _activity_query_source,
        now,
    )


def _soon_ending_activity_infos(now: datetime) -> list[ActivityInfo]:
    return soon_ending_activity_infos(
        _activity_query_source,
        now,
    )


def build_current_activity_message(
    now: datetime | None = None,
    *,
    limit: int | None = None,
    soon_only: bool = False,
) -> str:
    current_time = now or _now()
    return build_activity_query_message(
        _activity_query_source,
        current_time,
        limit=limit,
        soon_only=soon_only,
    )


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

    scheduled_count = schedule_reminder_jobs(
        scheduler,
        send_activity_reminder,
        reminders,
        grace_minutes=config.grace_minutes,
    )

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
    register_scan_jobs(
        scheduler,
        schedule_activity_reminders,
        enabled=get_activity_config().enabled,
        now=_now(),
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
