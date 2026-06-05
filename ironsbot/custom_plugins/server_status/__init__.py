# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
from nonebot import get_plugin_config, logger
from nonebot.exception import FinishedException
from nonebot.plugin import PluginMetadata, on_fullmatch
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.message_actions import (
    finish_event_reply,
    send_broadcast_message,
)
from ironsbot.custom_plugins.superuser_policy import (
    is_superuser,
    with_superuser_groups,
    with_superusers,
)
from ironsbot.utils.rule import no_reply

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.internal.matcher import Matcher

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
NOTICE_URL = "https://unity-notice.61.com/unity_notice/"
COMMANDS = ("开服查询", "开服了吗")
DEFAULT_UPDATE_WEEKDAY = 4
DEFAULT_START_TIME = time(hour=10)
DEFAULT_END_TIME = time(hour=15)
HTTP_TIMEOUT_SECONDS = 12.0
NOTICE_MAINTENANCE_TYPE = 3
BROADCAST_MESSAGE = "赛尔号已经开服了。"

HTML_TAG_PATTERN = re.compile(r"<[^>]*>")
MAINTENANCE_RANGE_PATTERN = re.compile(
    r"(?:(?P<year>\d{4})\s*年\s*)?"
    r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日?"
    r".{0,40}?"
    r"(?P<start_hour>\d{1,2})\s*(?:[:：]\s*(?P<start_minute>\d{1,2})|点(?P<start_minute_cn>\d{1,2})?分?)"
    r"\s*(?:-|~|\u2014|\u2013|至|到|\uff0d)\s*"
    r"(?:(?P<end_month>\d{1,2})\s*月\s*(?P<end_day>\d{1,2})\s*日?.{0,20}?)?"
    r"(?P<end_hour>\d{1,2})\s*(?:[:：]\s*(?P<end_minute>\d{1,2})|点(?P<end_minute_cn>\d{1,2})?分?)"
)


class Config(BaseModel):
    server_status_broadcast_groups: list[int] = Field(default_factory=list)
    server_status_broadcast_users: list[int] = Field(default_factory=list)
    server_status_broadcast_message: str = BROADCAST_MESSAGE
    server_status_broadcast_cooldown_minutes: int = Field(default=1440, ge=0)

    @field_validator(
        "server_status_broadcast_groups",
        "server_status_broadcast_users",
        mode="before",
    )
    @classmethod
    def coerce_int_list(cls, value: object) -> object:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return json.loads(stripped)
            return [
                int(part.strip())
                for part in stripped.split(",")
                if part.strip()
            ]
        return value

    @field_validator(
        "server_status_broadcast_groups",
        "server_status_broadcast_users",
    )
    @classmethod
    def normalize_int_list(cls, value: list[int]) -> list[int]:
        result: list[int] = []
        for item in value:
            if item > 0 and item not in result:
                result.append(item)
        return result

    @field_validator("server_status_broadcast_message")
    @classmethod
    def normalize_broadcast_message(cls, value: str) -> str:
        message = value.strip()
        return message or BROADCAST_MESSAGE


__plugin_meta__ = PluginMetadata(
    name="开服查询",
    description="查询赛尔号维护公告，并按周五更新窗口判断是否可能已开服",
    usage="""命令：
  开服了吗 / 开服查询 — 查询当前是否仍有维护公告

说明：
  优先解析官方开服公告中的维护时间；没有公告时按周五 10:00-15:00 默认更新窗口兜底。
  如果查询结果判断为已开服，会向 SERVER_STATUS_BROADCAST_GROUPS
  和 SERVER_STATUS_BROADCAST_USERS 配置的目标广播。""",
    config=Config,
    supported_adapters={"~onebot.v11"},
)


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    start: datetime
    end: datetime


@dataclass(slots=True)
class OpenBroadcastState:
    last_at: datetime | None = None


plugin_config = get_plugin_config(Config)
_open_broadcast_state = OpenBroadcastState()

server_status_matcher = on_fullmatch(
    COMMANDS,
    rule=no_reply(),
    priority=1,
    block=True,
)


@server_status_matcher.handle()
async def handle_server_status(matcher: Matcher, event: MessageEvent) -> None:
    now = _now()

    try:
        notice_text = await fetch_server_notice_text()
    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=True).warning("开服公告读取失败")
        await finish_event_reply(
            matcher,
            event,
            _build_fetch_failed_reply(now, e),
        )
        return

    if notice_text:
        await finish_event_reply(
            matcher,
            event,
            _build_notice_reply(notice_text, now),
        )
        return

    await _broadcast_opened(event, now=now)
    await finish_event_reply(
        matcher,
        event,
        _build_no_notice_reply(now),
    )


async def fetch_server_notice_text() -> str | None:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS),
    ) as client:
        response = await client.get(NOTICE_URL)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, list):
        return None

    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("type") == NOTICE_MAINTENANCE_TYPE:
            text = item.get("text")
            if isinstance(text, str):
                return _clean_notice_text(text)

    return None


def _build_notice_reply(notice_text: str, now: datetime) -> str:
    window = _parse_maintenance_window(notice_text, now)
    if window is None:
        return f"检测到维护公告，按官方公告为准：\n{notice_text}"

    if now < window.start:
        status = "还没到公告维护时间。"
    elif now <= window.end:
        status = f"维护中，预计 {_format_datetime(window.end)} 开服。"
    else:
        status = "公告仍在，但已超过公告结束时间，可能延迟开服。"

    return (
        f"{status}\n"
        "公告时间："
        f"{_format_datetime(window.start)} ~ {_format_datetime(window.end)}\n\n"
        f"{notice_text}"
    )


def _build_no_notice_reply(now: datetime) -> str:
    if _is_default_update_window(now):
        return (
            "没有读到维护公告，可能已经开服了哦~\n"
            "当前仍在周五默认更新窗口（10:00-15:00），如果官方临时调整，以公告为准。"
        )

    return "开服了哦~"


async def _broadcast_opened(event: MessageEvent, *, now: datetime) -> None:
    if not _should_broadcast_opened(now):
        return

    group_ids = with_superuser_groups(plugin_config.server_status_broadcast_groups)
    user_ids = with_superusers(plugin_config.server_status_broadcast_users)
    if not group_ids and not user_ids:
        logger.info("server status open broadcast skipped: no targets")
        return

    if not _can_trigger_open_broadcast(event, group_ids=group_ids, user_ids=user_ids):
        logger.info("server status open broadcast skipped: trigger not allowed")
        return

    if _is_open_broadcast_in_cooldown(now):
        logger.info("server status open broadcast skipped: cooldown")
        return

    summary = await send_broadcast_message(
        plugin_config.server_status_broadcast_message,
        group_ids=group_ids,
        private_user_ids=user_ids,
        action_name="server status open broadcast",
        interval_seconds=1.2,
    )
    if summary.succeeded:
        _open_broadcast_state.last_at = now


def _should_broadcast_opened(now: datetime) -> bool:
    return (
        now.weekday() == DEFAULT_UPDATE_WEEKDAY
        and now.time() >= DEFAULT_START_TIME
    )


def _can_trigger_open_broadcast(
    event: MessageEvent,
    *,
    group_ids: list[int],
    user_ids: list[int],
) -> bool:
    if is_superuser(event.user_id):
        return True

    group_id = getattr(event, "group_id", None)
    if group_id is not None:
        return int(group_id) in group_ids

    return event.user_id in user_ids


def _is_open_broadcast_in_cooldown(now: datetime) -> bool:
    if _open_broadcast_state.last_at is None:
        return False

    cooldown_minutes = plugin_config.server_status_broadcast_cooldown_minutes
    if cooldown_minutes <= 0:
        return False

    return now - _open_broadcast_state.last_at < timedelta(minutes=cooldown_minutes)


def _build_fetch_failed_reply(now: datetime, error: Exception) -> str:
    error_name = error.__class__.__name__
    if _is_default_update_window(now):
        return (
            f"⚠️ 没读到开服公告（{error_name}）。\n"
            "当前在周五默认更新窗口（10:00-15:00），建议稍后再试。"
        )

    return f"开服了哦~（公告读取失败：{error_name}）"


def _parse_maintenance_window(text: str, now: datetime) -> MaintenanceWindow | None:
    match = MAINTENANCE_RANGE_PATTERN.search(text)
    if match is None:
        return None

    year = _int_group(match, "year", now.year)
    month = _int_group(match, "month", now.month)
    day = _int_group(match, "day", now.day)
    end_month = _int_group(match, "end_month", month)
    end_day = _int_group(match, "end_day", day)

    start = _safe_datetime(
        year=year,
        month=month,
        day=day,
        hour=_int_group(match, "start_hour", DEFAULT_START_TIME.hour),
        minute=_minute_group(match, "start_minute", "start_minute_cn"),
    )
    end = _safe_datetime(
        year=year,
        month=end_month,
        day=end_day,
        hour=_int_group(match, "end_hour", DEFAULT_END_TIME.hour),
        minute=_minute_group(match, "end_minute", "end_minute_cn"),
    )
    if start is None or end is None:
        return None

    return MaintenanceWindow(start=start, end=end)


def _safe_datetime(
    *,
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
) -> datetime | None:
    try:
        return datetime(year, month, day, hour, minute, tzinfo=LOCAL_TZ)
    except ValueError:
        return None


def _int_group(match: re.Match[str], name: str, default: int) -> int:
    value = match.group(name)
    if value is None or value == "":
        return default
    return int(value)


def _minute_group(
    match: re.Match[str],
    colon_name: str,
    chinese_name: str,
) -> int:
    return _int_group(match, colon_name, _int_group(match, chinese_name, 0))


def _is_default_update_window(now: datetime) -> bool:
    return (
        now.weekday() == DEFAULT_UPDATE_WEEKDAY
        and DEFAULT_START_TIME <= now.time() < DEFAULT_END_TIME
    )


def _clean_notice_text(text: str) -> str:
    cleaned = HTML_TAG_PATTERN.sub("", text)
    return cleaned.replace("\\n", "\n").strip()


def _format_datetime(value: datetime) -> str:
    return value.strftime("%m-%d %H:%M")


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)
