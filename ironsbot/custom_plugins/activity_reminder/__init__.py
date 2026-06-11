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
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ironsbot.services.activity.commands import (
    is_current_activity_query_text,
    is_soon_ending_activity_query_text,
)
from ironsbot.services.activity.formatting import (
    format_activity_line,
    format_activity_list,
)
from ironsbot.services.activity.models import (
    ActivityDeadline,
    ActivityInfo,
    ActivityInfoCache,
    ActivityReminder,
)
from ironsbot.services.activity.notice import (
    offer_blocks,
    offer_end_time,
    offer_window_from_blocks,
)
from ironsbot.services.activity.planning import (
    activity_deadline,
    activity_is_soon_ending,
    activity_sort_end_time,
    build_scheduled_reminders,
    filter_valid_reminders,
    group_by_send_time,
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


_logged_warnings: set[str] = set()
_activity_info_cache = ActivityInfoCache()
_activity_reminder_runtime_state: dict[str, Any] = {
    "registered": False,
    "scheduler": None,
}
_ACTIVITY_REQUIRED_COLUMNS = frozenset(
    {"id", "name", "end_time", "is_show", "sort_order"}
)


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


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=LOCAL_TZ)
    elif isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text_value.replace("T", " "))
            except ValueError:
                return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _warn_activity_data_unavailable(key: str, reason: str) -> None:
    if key in _logged_warnings:
        return

    logger.warning(f"activity reminder skipped: {reason}")
    _logged_warnings.add(key)


def _activity_table_columns(session: Any) -> set[str]:
    rows = session.execute(text("PRAGMA table_info(activity)")).mappings().all()
    return {str(row["name"]) for row in rows if row.get("name") is not None}


def _load_activity_rows() -> list[Mapping[str, Any]]:
    gen = db_manager.get_session(SEERAPI_DB_NAME)
    if gen is None:
        _warn_activity_data_unavailable(
            "missing_session",
            "SeerAPI database not ready",
        )
        return []

    where_clause = "WHERE end_time IS NOT NULL"
    if get_activity_config().only_shown:
        where_clause += " AND COALESCE(is_show, 0) != 0"

    try:
        session = next(gen)
        columns = _activity_table_columns(session)
        if not columns:
            _warn_activity_data_unavailable(
                "missing_table",
                (
                    "activity table missing in SeerAPI database; run /更新数据 "
                    "after the data release is available, or set "
                    "activity.enabled=false"
                ),
            )
            return []

        missing_columns = _ACTIVITY_REQUIRED_COLUMNS - columns
        if missing_columns:
            _warn_activity_data_unavailable(
                "invalid_schema",
                (
                    "activity table schema is missing columns: "
                    f"{', '.join(sorted(missing_columns))}"
                ),
            )
            return []

        select_column_names = ["id", "name"]
        if "start_time" in columns:
            select_column_names.append("start_time")
        select_column_names.extend(["end_time", "is_show", "sort_order"])

        rows = session.execute(
            text(
                f"SELECT {', '.join(select_column_names)} "
                f"FROM activity {where_clause} "
                "ORDER BY end_time, sort_order, id"
            )
        ).mappings().all()
    except OperationalError as e:
        logger.opt(exception=True).debug("activity reminder query failed")
        _warn_activity_data_unavailable(
            "query_failed",
            f"activity table query failed: {e.__class__.__name__}",
        )
        return []
    finally:
        gen.close()

    _logged_warnings.discard("missing_session")
    _logged_warnings.discard("missing_table")
    _logged_warnings.discard("invalid_schema")
    _logged_warnings.discard("query_failed")
    return list(rows)


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

    activities: list[ActivityInfo] = []
    for row in _load_activity_rows():
        end_time = _parse_datetime(row.get("end_time"))
        if end_time is None or end_time <= now:
            continue

        start_time = _parse_datetime(row.get("start_time"))
        if start_time is not None and start_time > now:
            continue

        activity = ActivityInfo(
            activity_id=int(row["id"]),
            name=str(row.get("name") or f"活动 {row['id']}"),
            start_time=start_time,
            end_time=end_time,
            sort_order=int(row.get("sort_order") or 0),
        )
        try:
            activity_offer_blocks = offer_blocks(activity, now)
            offer_window = offer_window_from_blocks(activity_offer_blocks)
            activity_offer_end_time = offer_end_time(
                activity,
                activity_offer_blocks,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning(
                "activity reminder offer parsing failed for "
                f"activity {activity.activity_id}: {activity.name}"
            )
            offer_window = None
            activity_offer_end_time = None
        activities.append(
            ActivityInfo(
                activity_id=activity.activity_id,
                name=activity.name,
                start_time=activity.start_time,
                end_time=activity.end_time,
                sort_order=activity.sort_order,
                offer_label=offer_window[0] if offer_window else None,
                offer_window_days=offer_window[1] if offer_window else None,
                offer_end_time=activity_offer_end_time,
            )
        )

    sorted_activities = sorted(
        activities,
        key=lambda activity: (
            _activity_sort_end_time(activity),
            activity.sort_order,
            activity.activity_id,
        ),
    )
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
    try:
        return get_activity_config().message.format(
            lead_hours=lead_hours,
            activity_count=len(reminders),
            activity_list=format_activity_list(reminders),
        )
    except (KeyError, IndexError, ValueError) as e:
        logger.warning(f"activity reminder template failed: {e}")
        return DEFAULT_MESSAGE_TEMPLATE.format(
            lead_hours=lead_hours,
            activity_list=format_activity_list(reminders),
        )


def _group_by_send_time(
    reminders: Iterable[ActivityReminder],
) -> dict[tuple[int, datetime], list[ActivityReminder]]:
    return group_by_send_time(reminders)


def _current_activity_by_id(now: datetime) -> dict[int, ActivityInfo]:
    return {
        activity.activity_id: activity
        for activity in _soon_ending_activity_infos(now)
    }


def _filter_valid_reminders_before_send(
    reminders: Iterable[ActivityReminder],
    *,
    now: datetime,
) -> list[ActivityReminder]:
    activity_by_id = _current_activity_by_id(now)
    return filter_valid_reminders(
        reminders,
        now=now,
        activity_by_id=activity_by_id,
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
