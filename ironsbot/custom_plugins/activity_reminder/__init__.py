# SPDX-License-Identifier: MIT
import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from nonebot import get_plugin_config, on_message, require
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ironsbot.custom_plugins.message_actions import (
    finish_event_reply,
    send_broadcast_message,
)
from ironsbot.custom_plugins.superuser_policy import (
    with_superuser_groups,
    with_superusers,
)
from ironsbot.utils.rule import no_reply

require("ironsbot.plugins.seer_data")
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from ironsbot.plugins.db_sync.manager import db_manager

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SEERAPI_DB_NAME = "seerapi"
DEFAULT_MESSAGE_TEMPLATE = "⏰ 本周活动将在约 {lead_hours} 小时后结束\n{activity_list}"
ADMIN_COMMAND_PREFIXES = ("/",)
CURRENT_ACTIVITY_COMMANDS = ("当前活动", "活动列表", "活动时间")
SOON_ENDING_ACTIVITY_COMMANDS = (
    "快结束活动",
    "即将结束活动",
    "即将结束",
    "本周结束活动",
    "本周活动",
    "活动快结束",
)
SOON_ENDING_THRESHOLD = timedelta(days=7)
REMINDER_SEND_DELAY = timedelta(minutes=10)
REMINDER_DISPATCH_TOLERANCE = timedelta(minutes=1)
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
MINUTES_PER_DAY = HOURS_PER_DAY * MINUTES_PER_HOUR


def _coerce_int_list(value: object) -> object:
    if not isinstance(value, str):
        return value

    raw = value.strip()
    if not raw:
        return []

    if raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return value

    return [item.strip() for item in raw.split(",") if item.strip()]


def _unique_positive_ints(values: Iterable[int]) -> list[int]:
    return [
        value
        for value in dict.fromkeys(values)
        if value > 0
    ]


def _normalize_command_text(text_value: str) -> str:
    return "".join(text_value.split()).lower()


NORMALIZED_CURRENT_ACTIVITY_COMMANDS = {
    _normalize_command_text(command)
    for command in CURRENT_ACTIVITY_COMMANDS
}
NORMALIZED_SOON_ENDING_ACTIVITY_COMMANDS = {
    _normalize_command_text(command)
    for command in SOON_ENDING_ACTIVITY_COMMANDS
}
def _strip_admin_command_prefix(text_value: str) -> str | None:
    stripped = text_value.strip()
    for prefix in ADMIN_COMMAND_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


async def _is_current_activity_query_command(event: Event) -> bool:
    command = _strip_admin_command_prefix(event.get_plaintext())
    if command is None:
        return False

    normalized = _normalize_command_text(command)
    return normalized in NORMALIZED_CURRENT_ACTIVITY_COMMANDS


async def _is_soon_ending_activity_query_command(event: Event) -> bool:
    command = _strip_admin_command_prefix(event.get_plaintext())
    if command is None:
        return False

    normalized = _normalize_command_text(command)
    return normalized in NORMALIZED_SOON_ENDING_ACTIVITY_COMMANDS


class Config(BaseModel):
    activity_reminder: bool = True
    activity_reminder_groups: list[int] = Field(default_factory=list)
    activity_reminder_users: list[int] = Field(default_factory=list)
    activity_reminder_lead_hours: list[int] = Field(
        default_factory=lambda: [11, 1]
    )
    activity_reminder_grace_minutes: int = Field(default=15, ge=1)
    activity_reminder_only_shown: bool = True
    activity_reminder_cache_path: Path = Path(
        "data/activity_reminder/sent.sqlite"
    )
    activity_reminder_message: str = DEFAULT_MESSAGE_TEMPLATE

    @field_validator(
        "activity_reminder_groups",
        "activity_reminder_users",
        "activity_reminder_lead_hours",
        mode="before",
    )
    @classmethod
    def coerce_int_list(cls, value: object) -> object:
        return _coerce_int_list(value)

    @field_validator(
        "activity_reminder_groups",
        "activity_reminder_users",
        "activity_reminder_lead_hours",
    )
    @classmethod
    def normalize_int_list(cls, value: list[int]) -> list[int]:
        return _unique_positive_ints(value)


plugin_config = get_plugin_config(Config)

__plugin_meta__ = PluginMetadata(
    name="活动结束提醒",
    description="从 SeerAPI 活动数据读取结束时间，提前提醒活动即将结束",
    usage=(
        "【活动结束提醒】\n"
        "按 ACTIVITY_REMINDER_LEAD_HOURS 配置提前提醒活动即将结束。\n"
        "目标群由 ACTIVITY_REMINDER_GROUPS 配置，ADMIN_GROUPS 自动包含；"
        "目标用户由 ACTIVITY_REMINDER_USERS 配置，SUPERUSERS 自动包含。\n"
        "超级管理员可发送 /当前活动、/活动列表、/活动时间 查看当前活动和剩余时间；"
        "发送 /快结束活动 查看不足 7 天结束的活动。"
    ),
    config=Config,
)


@dataclass(frozen=True, slots=True)
class ActivityInfo:
    activity_id: int
    name: str
    start_time: datetime | None
    end_time: datetime
    sort_order: int


@dataclass(frozen=True, slots=True)
class ActivityReminder:
    activity_id: int
    name: str
    end_time: datetime
    lead_hours: int
    send_time: datetime


_logged_warnings: set[str] = set()


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _cache_path() -> Path:
    path = plugin_config.activity_reminder_cache_path
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect_cache() -> sqlite3.Connection:
    conn = sqlite3.connect(_cache_path())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_activity_reminders (
            activity_id INTEGER NOT NULL,
            end_time TEXT NOT NULL,
            lead_hours INTEGER NOT NULL,
            sent_at TEXT NOT NULL,
            PRIMARY KEY (activity_id, end_time, lead_hours)
        )
        """
    )
    conn.commit()
    return conn


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


def _load_activity_rows() -> list[Mapping[str, Any]]:
    gen = db_manager.get_session(SEERAPI_DB_NAME)
    if gen is None:
        if "missing_session" not in _logged_warnings:
            logger.warning("activity reminder skipped: SeerAPI database not ready")
            _logged_warnings.add("missing_session")
        return []

    where_clause = "WHERE end_time IS NOT NULL"
    if plugin_config.activity_reminder_only_shown:
        where_clause += " AND COALESCE(is_show, 0) != 0"

    try:
        session = next(gen)
        try:
            rows = session.execute(
                text(
                    "SELECT id, name, start_time, end_time, is_show, sort_order "
                    f"FROM activity {where_clause} "
                    "ORDER BY end_time, sort_order, id"
                )
            ).mappings().all()
        except OperationalError as e:
            if "start_time" not in str(e):
                raise
            rows = session.execute(
                text(
                    "SELECT id, name, end_time, is_show, sort_order "
                    f"FROM activity {where_clause} "
                    "ORDER BY end_time, sort_order, id"
                )
            ).mappings().all()
    except OperationalError as e:
        if "missing_table" not in _logged_warnings:
            logger.warning(
                "activity reminder skipped: activity table unavailable: "
                f"{e}"
            )
            _logged_warnings.add("missing_table")
        return []
    finally:
        gen.close()

    _logged_warnings.discard("missing_session")
    _logged_warnings.discard("missing_table")
    return list(rows)


def _active_activity_infos(now: datetime) -> list[ActivityInfo]:
    activities: list[ActivityInfo] = []
    for row in _load_activity_rows():
        end_time = _parse_datetime(row.get("end_time"))
        if end_time is None or end_time <= now:
            continue

        start_time = _parse_datetime(row.get("start_time"))
        if start_time is not None and start_time > now:
            continue

        activities.append(
            ActivityInfo(
                activity_id=int(row["id"]),
                name=str(row.get("name") or f"活动 {row['id']}"),
                start_time=start_time,
                end_time=end_time,
                sort_order=int(row.get("sort_order") or 0),
            )
        )

    return sorted(
        activities,
        key=lambda activity: (
            activity.end_time,
            activity.sort_order,
            activity.activity_id,
        ),
    )


def _soon_ending_activity_infos(now: datetime) -> list[ActivityInfo]:
    return [
        activity
        for activity in _active_activity_infos(now)
        if activity.end_time - now < SOON_ENDING_THRESHOLD
    ]


def _format_remaining_time(delta: timedelta) -> str:
    total_minutes = max(
        0,
        int(delta.total_seconds() // SECONDS_PER_MINUTE),
    )
    days, day_remainder = divmod(total_minutes, MINUTES_PER_DAY)
    hours, minutes = divmod(day_remainder, MINUTES_PER_HOUR)

    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes or not parts:
        parts.append(f"{minutes}分")
    return "".join(parts)


def _format_activity_period(activity: ActivityInfo) -> str:
    end_text = f"{activity.end_time:%m-%d %H:%M}"
    if activity.start_time is None:
        return f"结束：{end_text}"
    return f"{activity.start_time:%m-%d %H:%M} ~ {end_text}"


def _format_activity_line(
    index: int,
    activity: ActivityInfo,
    remaining_text: str,
    *,
    soon_only: bool,
) -> list[str]:
    if soon_only:
        return [
            (
                f"{index}. {activity.name}：结束时间："
                f"{activity.end_time:%m-%d %H:%M} | 剩余：{remaining_text}"
            )
        ]

    period_text = _format_activity_period(activity)
    return [
        f"{index}. {activity.name}",
        f"   持续：{period_text} | 剩余：{remaining_text}",
    ]


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
        remaining_text = _format_remaining_time(activity.end_time - current_time)
        lines.extend(
            _format_activity_line(
                index,
                activity,
                remaining_text,
                soon_only=soon_only,
            )
        )

    hidden_count = len(activities) - len(shown_activities)
    if limit is not None and hidden_count > 0:
        lines.append(f"...还有 {hidden_count} 个活动未显示")
    return "\n".join(lines)


def _build_scheduled_reminders(now: datetime) -> list[ActivityReminder]:
    reminders: list[ActivityReminder] = []

    for activity in _soon_ending_activity_infos(now):
        for lead_hours in plugin_config.activity_reminder_lead_hours:
            send_time = (
                activity.end_time
                - timedelta(hours=lead_hours)
                + REMINDER_SEND_DELAY
            )
            if send_time < now:
                continue

            reminders.append(
                ActivityReminder(
                    activity_id=activity.activity_id,
                    name=activity.name,
                    end_time=activity.end_time,
                    lead_hours=lead_hours,
                    send_time=send_time,
                )
            )

    return reminders


def _reminder_key(reminder: ActivityReminder) -> tuple[int, str, int]:
    return (
        reminder.activity_id,
        reminder.end_time.isoformat(),
        reminder.lead_hours,
    )


def _filter_unsent(
    reminders: Iterable[ActivityReminder],
) -> list[ActivityReminder]:
    with _connect_cache() as conn:
        unsent: list[ActivityReminder] = []
        for reminder in reminders:
            activity_id, end_time, lead_hours = _reminder_key(reminder)
            sent = conn.execute(
                """
                SELECT 1 FROM sent_activity_reminders
                WHERE activity_id = ? AND end_time = ? AND lead_hours = ?
                """,
                (activity_id, end_time, lead_hours),
            ).fetchone()
            if sent is None:
                unsent.append(reminder)
        return unsent


def _mark_sent(reminders: Iterable[ActivityReminder]) -> None:
    sent_at = _now().isoformat()
    with _connect_cache() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO sent_activity_reminders
            (activity_id, end_time, lead_hours, sent_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (*_reminder_key(reminder), sent_at)
                for reminder in reminders
            ],
        )
        conn.commit()


def _format_activity_list(reminders: list[ActivityReminder]) -> str:
    return "\n".join(
        f"{index}. {reminder.name}：{reminder.end_time:%Y-%m-%d %H:%M}"
        for index, reminder in enumerate(reminders, start=1)
    )


def _format_message(lead_hours: int, reminders: list[ActivityReminder]) -> str:
    try:
        return plugin_config.activity_reminder_message.format(
            lead_hours=lead_hours,
            activity_count=len(reminders),
            activity_list=_format_activity_list(reminders),
        )
    except (KeyError, IndexError, ValueError) as e:
        logger.warning(f"activity reminder template failed: {e}")
        return DEFAULT_MESSAGE_TEMPLATE.format(
            lead_hours=lead_hours,
            activity_list=_format_activity_list(reminders),
        )


def _group_by_send_time(
    reminders: Iterable[ActivityReminder],
) -> dict[tuple[int, datetime], list[ActivityReminder]]:
    grouped: dict[tuple[int, datetime], list[ActivityReminder]] = {}
    for reminder in reminders:
        grouped.setdefault((reminder.lead_hours, reminder.send_time), []).append(
            reminder
        )
    return grouped


def _current_activity_by_id(now: datetime) -> dict[int, ActivityInfo]:
    return {
        activity.activity_id: activity
        for activity in _soon_ending_activity_infos(now)
    }


def _is_reminder_still_valid(
    reminder: ActivityReminder,
    *,
    now: datetime,
    activity_by_id: dict[int, ActivityInfo],
) -> bool:
    if now > reminder.send_time + REMINDER_DISPATCH_TOLERANCE:
        return False

    current_activity = activity_by_id.get(reminder.activity_id)
    if current_activity is None:
        return False

    return current_activity.end_time == reminder.end_time


def _filter_valid_reminders_before_send(
    reminders: Iterable[ActivityReminder],
    *,
    now: datetime,
) -> list[ActivityReminder]:
    activity_by_id = _current_activity_by_id(now)
    return [
        reminder
        for reminder in reminders
        if _is_reminder_still_valid(
            reminder,
            now=now,
            activity_by_id=activity_by_id,
        )
    ]


async def send_activity_reminder(
    *,
    lead_hours: int,
    reminders: list[ActivityReminder],
) -> None:
    reminders = _filter_valid_reminders_before_send(reminders, now=_now())
    if not reminders:
        logger.info(
            f"activity ending reminder {lead_hours}h skipped: no valid reminders"
        )
        return

    target_groups = with_superuser_groups(plugin_config.activity_reminder_groups)
    target_users = with_superusers(plugin_config.activity_reminder_users)
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
        _mark_sent(reminders)


def _reminder_job_id(lead_hours: int, send_time: datetime) -> str:
    return f"activity_reminder_{lead_hours}h_{int(send_time.timestamp())}"


async def schedule_activity_reminders() -> None:
    if not plugin_config.activity_reminder:
        return

    reminders = _filter_unsent(_build_scheduled_reminders(_now()))
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
    rule=Rule(_is_soon_ending_activity_query_command) & no_reply(),
    priority=5,
    block=True,
)


@current_activity_matcher.handle()
async def handle_current_activity_query(
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        current_activity_matcher,
        event,
        build_current_activity_message(),
    )


@soon_ending_activity_matcher.handle()
async def handle_soon_ending_activity_query(event: MessageEvent) -> None:
    await finish_event_reply(
        soon_ending_activity_matcher,
        event,
        build_current_activity_message(soon_only=True),
    )


if plugin_config.activity_reminder:
    scheduler.add_job(
        schedule_activity_reminders,
        "date",
        id="activity_reminder_startup_scan",
        replace_existing=True,
        next_run_time=_now() + timedelta(seconds=30),
    )
    scheduler.add_job(
        schedule_activity_reminders,
        "cron",
        id="activity_reminder_daily_scan",
        replace_existing=True,
        hour=0,
        minute=0,
        second=0,
    )
