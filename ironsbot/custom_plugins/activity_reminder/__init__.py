# SPDX-License-Identifier: MIT
import html
import json
import re
import sqlite3
import urllib.error
import urllib.request
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
    is_custom_feature_event_allowed,
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
UNITY_NOTICE_URL = "https://unity-notice.61.com/unity_notice/"
UNITY_NOTICE_TIMEOUT_SECONDS = 8
UNITY_NOTICE_CACHE_TTL = timedelta(minutes=30)
NOTICE_ACTIVITY_BLOCK_CHARS = 900
NOTICE_ACTIVITY_LOOKBEHIND_CHARS = 80
DAYS_PER_WEEK = 7
DEFAULT_OFFER_WINDOW_WEEKS = 1
LIMITED_OFFER_KEYWORDS = (
    "优惠",
    "特惠",
    "折扣",
    "降价",
    "减免",
    "恢复至原价",
    "价格恢复",
    "限时",
)
OFFER_WINDOW_KEYWORDS = (
    "首周",
    "第一周",
    "首月",
    "第一月",
    "截止至",
    "更新前",
    "购买时间",
    "价格恢复",
    "恢复至原价",
    "更新后恢复",
    "回复至原价",
)
SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
MINUTES_PER_DAY = HOURS_PER_DAY * MINUTES_PER_HOUR


@dataclass(slots=True)
class NoticeCache:
    text: str = ""
    expires_at: datetime | None = None


_notice_cache = NoticeCache()

CHINESE_NUMBER_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


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
    offer_label: str | None = None
    offer_window_days: int | None = None
    offer_end_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class ActivityReminder:
    activity_id: int
    name: str
    end_time: datetime
    lead_hours: int
    send_time: datetime
    end_label: str = "结束时间"
    display_end_time: bool = True


@dataclass(frozen=True, slots=True)
class ActivityDeadline:
    end_time: datetime
    label: str
    display_end_time: bool


_logged_warnings: set[str] = set()


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _normalize_notice_text(text_value: str) -> str:
    return html.unescape(
        text_value
        .replace("\\r", "\n")
        .replace("\\n", "\n")
        .replace("\\/", "/")
    )


def _fetch_unity_notice_text(now: datetime) -> str:
    if (
        _notice_cache.expires_at is not None
        and _notice_cache.expires_at > now
    ):
        return _notice_cache.text

    try:
        request = urllib.request.Request(
            UNITY_NOTICE_URL,
            headers={"User-Agent": "IronsBot activity reminder"},
        )
        with urllib.request.urlopen(
            request,
            timeout=UNITY_NOTICE_TIMEOUT_SECONDS,
        ) as response:
            raw_text = response.read().decode("utf-8", "replace")
    except (OSError, urllib.error.URLError) as e:
        logger.warning(f"activity notice fetch failed: {e}")
        _notice_cache.expires_at = now + timedelta(minutes=5)
        return _notice_cache.text

    _notice_cache.text = _normalize_notice_text(raw_text)
    _notice_cache.expires_at = now + UNITY_NOTICE_CACHE_TTL
    return _notice_cache.text


def _activity_notice_blocks(activity_name: str, notice_text: str) -> list[str]:
    escaped_name = re.escape(activity_name)
    blocks: list[str] = []
    for pattern in (
        rf"◇\s*「{escaped_name}」",
        rf"\b\d+(?:\.|\uFF0E)\s*{escaped_name}",
        escaped_name,
    ):
        for match in re.finditer(pattern, notice_text):
            start = max(0, match.start() - NOTICE_ACTIVITY_LOOKBEHIND_CHARS)
            relative_match_start = match.start() - start
            block = notice_text[
                start : match.start() + NOTICE_ACTIVITY_BLOCK_CHARS
            ]
            next_item = re.search(
                r"\n\s*\d+(?:\.|\uFF0E)\s*",
                block[relative_match_start + 1 :],
            )
            if next_item is not None:
                block = block[: relative_match_start + next_item.start() + 1]
            blocks.append(block)
        if blocks:
            break
    return blocks


def _offer_blocks(activity: ActivityInfo, now: datetime) -> list[str]:
    if activity.start_time is None:
        return []

    notice_text = _fetch_unity_notice_text(now)
    if not notice_text:
        return []

    return [
        block
        for block in _activity_notice_blocks(activity.name, notice_text)
        if (
            _block_has_limited_offer(block)
            and (
                _offer_window_from_block(block) is not None
                or _parse_offer_deadline_with_hour(block, activity) is not None
                or _block_has_offer_window(block)
            )
        )
    ]


def _parse_week_count(text_value: str) -> int | None:
    if text_value.isdigit():
        return int(text_value)
    return CHINESE_NUMBER_MAP.get(text_value)


def _datetime_from_match(
    match: re.Match[str],
    activity: ActivityInfo,
    *,
    default_hour: int,
    default_minute: int = 0,
) -> datetime | None:
    if activity.start_time is None:
        return None

    year = int(match.groupdict().get("year") or activity.start_time.year)
    month = int(match.group("month"))
    day = int(match.group("day"))
    hour_text = match.groupdict().get("hour")
    minute_text = match.groupdict().get("minute")
    hour = default_hour
    if hour_text is not None:
        hour = 0 if hour_text == "零" else int(hour_text)
    minute = int(minute_text) if minute_text is not None else default_minute
    second_text = match.groupdict().get("second")
    second = int(second_text) if second_text is not None else 0
    try:
        if hour == HOURS_PER_DAY and minute == 0 and second == 0:
            return datetime(
                year,
                month,
                day,
                0,
                0,
                tzinfo=LOCAL_TZ,
            ) + timedelta(days=1)
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            tzinfo=LOCAL_TZ,
        )
    except ValueError:
        return None


def _block_has_limited_offer(block: str) -> bool:
    return any(keyword in block for keyword in LIMITED_OFFER_KEYWORDS)


def _block_has_offer_window(block: str) -> bool:
    return any(keyword in block for keyword in OFFER_WINDOW_KEYWORDS)


def _offer_window_from_block(block: str) -> tuple[str, int] | None:  # noqa: PLR0911
    if not _block_has_limited_offer(block):
        return None

    week_match = re.search(
        r"(?P<label>(?:首|前)(?P<count>\d+|[一二两三四五六七八九十])周)",
        block,
    )
    if week_match is not None:
        week_count = _parse_week_count(week_match.group("count"))
        if week_count is not None and week_count > 0:
            return (
                f"{week_match.group('label')}优惠",
                week_count * DAYS_PER_WEEK,
            )

    day_match = re.search(
        r"(?P<label>(?:首|前)(?P<count>\d+|[一二两三四五六七八九十])天)",
        block,
    )
    if day_match is not None:
        day_count = _parse_week_count(day_match.group("count"))
        if day_count is not None and day_count > 0:
            return f"{day_match.group('label')}优惠", day_count

    if "首周" in block or "第一周" in block:
        return (
            "首周优惠",
            DEFAULT_OFFER_WINDOW_WEEKS * DAYS_PER_WEEK,
        )

    month_match = re.search(
        r"(?P<label>(?:首|前)(?P<count>\d+|[一二两三四五六七八九十])月)",
        block,
    )
    if month_match is not None:
        month_count = _parse_week_count(month_match.group("count"))
        if month_count is not None and month_count > 0:
            return f"{month_match.group('label')}优惠", month_count * 30

    if "首月" in block or "第一月" in block:
        return "首月优惠", 30

    return None


def _offer_window_from_blocks(blocks: list[str]) -> tuple[str, int] | None:
    for block in blocks:
        offer_window = _offer_window_from_block(block)
        if offer_window is not None:
            return offer_window
    return None


def _parse_offer_deadline_with_hour(  # noqa: PLR0911
    block: str,
    activity: ActivityInfo,
) -> datetime | None:
    if activity.start_time is None:
        return None

    match = re.search(
        r"截止至\s*(?:(?P<year>\d{4})[.年])?"
        r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
        r"\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{1,2})"
        r"(?::(?P<second>\d{1,2}))?",
        block,
    )
    if match is not None:
        return _datetime_from_match(match, activity, default_hour=0)

    match = re.search(
        r"截止至\s*(?:(?P<year>\d{4})[.年])?"
        r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
        r"\s*(?P<hour>\d{1,2}|零)点"
        r"(?:(?P<minute>\d{1,2})分)?前",
        block,
    )
    if match is not None:
        return _datetime_from_match(match, activity, default_hour=0)

    match = re.search(
        r"(?:(?P<year>\d{4})[.年])?"
        r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
        r"\s*(?P<hour>\d{1,2}|零)?点?后(?:价格)?(?:恢复|回复)",
        block,
    )
    if match is not None:
        return _datetime_from_match(match, activity, default_hour=0)

    match = re.search(
        r"(?:(?P<year>\d{4})[.年])?"
        r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
        r"\s*(?:更新前|更新后(?:价格)?(?:恢复|回复))",
        block,
    )
    if match is not None:
        return _datetime_from_match(match, activity, default_hour=10)

    match = re.search(
        r"(?:购买时间|生效时间|限时生效|活动时间)[：:，,\s]*"
        r"(?:(?P<start_year>\d{4})[.年])?"
        r"\d{1,2}月\d{1,2}日(?:更新后)?[-~至到]+"
        r"(?:(?P<year>\d{4})[.年])?"
        r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
        r"(?:(?P<hour>\d{1,2}|零)点)?(?:更新前)?",
        block,
    )
    if match is not None:
        return _datetime_from_match(match, activity, default_hour=10)

    return None


def _offer_end_time(
    activity: ActivityInfo,
    blocks: list[str],
) -> datetime | None:
    for block in blocks:
        offer_end_time = _parse_offer_deadline_with_hour(block, activity)
        if offer_end_time is not None and offer_end_time < activity.end_time:
            return offer_end_time
    return None


def _fallback_offer_window_open(activity: ActivityInfo, now: datetime) -> bool:
    fallback_end = _fallback_offer_window_end(activity)
    if fallback_end is None:
        return False
    return activity.start_time <= now < fallback_end


def _fallback_offer_window_end(activity: ActivityInfo) -> datetime | None:
    if (
        activity.offer_label is None
        or activity.offer_window_days is None
        or activity.start_time is None
    ):
        return None
    return activity.start_time + timedelta(days=activity.offer_window_days)


def _activity_deadline(
    activity: ActivityInfo,
    now: datetime,
) -> ActivityDeadline | None:
    if activity.offer_end_time is not None and activity.offer_end_time > now:
        return ActivityDeadline(
            end_time=activity.offer_end_time,
            label=f"{activity.offer_label or '限时优惠'}截至",
            display_end_time=True,
        )

    if now < activity.end_time and activity.end_time - now < SOON_ENDING_THRESHOLD:
        return ActivityDeadline(
            end_time=activity.end_time,
            label="结束时间",
            display_end_time=True,
        )

    fallback_end = (
        None
        if activity.offer_end_time is not None
        else _fallback_offer_window_end(activity)
    )
    if (
        fallback_end is not None
        and activity.start_time is not None
        and activity.start_time <= now < fallback_end
    ):
        return ActivityDeadline(
            end_time=fallback_end,
            label=activity.offer_label or "限时优惠",
            display_end_time=False,
        )

    return None


def _activity_is_soon_ending(activity: ActivityInfo, now: datetime) -> bool:
    return _activity_deadline(activity, now) is not None


def _activity_sort_end_time(
    activity: ActivityInfo,
    now: datetime | None = None,
) -> datetime:
    if now is not None:
        deadline = _activity_deadline(activity, now)
        if deadline is not None:
            return deadline.end_time
    return activity.offer_end_time or activity.end_time


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

        activity = ActivityInfo(
            activity_id=int(row["id"]),
            name=str(row.get("name") or f"活动 {row['id']}"),
            start_time=start_time,
            end_time=end_time,
            sort_order=int(row.get("sort_order") or 0),
        )
        offer_blocks = _offer_blocks(activity, now)
        offer_window = _offer_window_from_blocks(offer_blocks)
        activities.append(
            ActivityInfo(
                activity_id=activity.activity_id,
                name=activity.name,
                start_time=activity.start_time,
                end_time=activity.end_time,
                sort_order=activity.sort_order,
                offer_label=offer_window[0] if offer_window else None,
                offer_window_days=offer_window[1] if offer_window else None,
                offer_end_time=_offer_end_time(
                    activity,
                    offer_blocks,
                ),
            )
        )

    return sorted(
        activities,
        key=lambda activity: (
            _activity_sort_end_time(activity),
            activity.sort_order,
            activity.activity_id,
        ),
    )


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
    current_time: datetime,
    *,
    soon_only: bool,
) -> list[str]:
    if soon_only:
        deadline = _activity_deadline(activity, current_time)
        if deadline is not None and deadline.display_end_time:
            remaining_text = _format_remaining_time(
                deadline.end_time - current_time
            )
            return [
                (
                    f"{index}. {activity.name}：{deadline.label}："
                    f"{deadline.end_time:%m-%d %H:%M} | 剩余：{remaining_text}"
                )
            ]

        period_text = _format_activity_period(activity)
        offer_label = activity.offer_label or "限时优惠"
        return [
            (
                f"{index}. {activity.name}：{offer_label}见官方说明 | "
                f"活动：{period_text}"
            )
        ]

    period_text = _format_activity_period(activity)
    remaining_text = _format_remaining_time(activity.end_time - current_time)
    return [
        f"{index}. {activity.name}：{period_text} | 剩余：{remaining_text}",
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
        lines.extend(
            _format_activity_line(
                index,
                activity,
                current_time,
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
        deadline = _activity_deadline(activity, now)
        if deadline is None:
            continue

        for lead_hours in plugin_config.activity_reminder_lead_hours:
            send_time = (
                deadline.end_time
                - timedelta(hours=lead_hours)
                + REMINDER_SEND_DELAY
            )
            if send_time < now:
                continue

            reminders.append(
                ActivityReminder(
                    activity_id=activity.activity_id,
                    name=activity.name,
                    end_time=deadline.end_time,
                    lead_hours=lead_hours,
                    send_time=send_time,
                    end_label=deadline.label,
                    display_end_time=deadline.display_end_time,
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
    lines: list[str] = []
    for index, reminder in enumerate(reminders, start=1):
        if reminder.display_end_time:
            lines.append(
                f"{index}. {reminder.name}：{reminder.end_label}："
                f"{reminder.end_time:%Y-%m-%d %H:%M}"
            )
        else:
            lines.append(
                f"{index}. {reminder.name}：{reminder.end_label}见官方说明"
            )
    return "\n".join(lines)


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

    deadline = _activity_deadline(current_activity, now)
    if deadline is None:
        return False
    return (
        deadline.end_time == reminder.end_time
        and deadline.display_end_time == reminder.display_end_time
    )


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
    rule=(
        Rule(is_custom_feature_event_allowed)
        & Rule(_is_soon_ending_activity_query_command)
        & no_reply()
    ),
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
