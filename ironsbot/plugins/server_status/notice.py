# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import httpx

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
NOTICE_URL = "https://unity-notice.61.com/unity_notice/"
DEFAULT_START_TIME = time(hour=10)
DEFAULT_END_TIME = time(hour=15)
HTTP_TIMEOUT_SECONDS = 12.0
NOTICE_MAINTENANCE_TYPE = 3

HTML_TAG_PATTERN = re.compile(r"<[^>]*>")
MAINTENANCE_RANGE_PATTERN = re.compile(
    r"(?:(?P<year>\d{4})\s*年\s*)?"
    r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日"
    r".{0,40}?"
    r"(?P<start_hour>\d{1,2})\s*(?:[:：]\s*(?P<start_minute>\d{1,2})|点(?P<start_minute_cn>\d{1,2})?分?)"
    r"\s*(?:-|~|\u2014|\u2013|至|到|－)\s*"
    r"(?:(?P<end_month>\d{1,2})\s*月\s*(?P<end_day>\d{1,2})\s*日.{0,20}?)?"
    r"(?P<end_hour>\d{1,2})\s*(?:[:：]\s*(?P<end_minute>\d{1,2})|点(?P<end_minute_cn>\d{1,2})?分?)"
)


@dataclass(frozen=True, slots=True)
class MaintenanceWindow:
    start: datetime
    end: datetime


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


def _build_open_reply(
    now: datetime,
    *,
    notice_text: str | None = None,
    notice_error: Exception | None = None,
) -> str:
    lines = ["开服了哦~（机器人已登录游戏服务器）"]
    if notice_text:
        lines.extend(("", _build_notice_summary(notice_text, now)))
    if notice_error is not None:
        lines.extend(
            (
                "",
                f"公告读取失败：{notice_error.__class__.__name__}，但无头客户端已登录。",
            )
        )
    return "\n".join(lines)


def _build_notice_reply(notice_text: str) -> str:
    return notice_text


def _build_notice_summary(notice_text: str, now: datetime) -> str:
    window = _parse_maintenance_window(notice_text, now)
    if window is None:
        return f"检测到维护公告：{_short_notice_text(notice_text)}"

    if now < window.start:
        status = "还没到公告维护时间"
    elif now <= window.end:
        status = f"维护中，预计 {_format_datetime(window.end)} 开服"
    else:
        status = "公告仍在，但已超过公告结束时间，可能延迟开服"

    return (
        f"公告摘要：{status}\n"
        "公告时间："
        f"{_format_datetime(window.start)} ~ {_format_datetime(window.end)}\n"
        f"公告内容：{_short_notice_text(notice_text)}"
    )


def _build_no_notice_reply(now: datetime, *, headless_status: Any) -> str:
    if headless_status.connected:
        return _build_open_reply(now)

    return "可能还在维护、开服波动，或登录服/网络暂时不稳定。"


def _build_fetch_failed_reply(
    now: datetime,
    error: Exception,
    *,
    headless_status: Any,
) -> str:
    error_name = error.__class__.__name__
    if headless_status.connected:
        return _build_open_reply(now, notice_error=error)

    reason_text = _format_headless_unavailable_text(headless_status.reason)
    return (
        f"公告读取失败（{error_name}），机器人也没有登录游戏服务器，暂时不能确认已开服。\n"
        f"{reason_text}\n"
        "可能还在维护、开服波动，或登录服/网络暂时不稳定。"
    )


def _format_headless_unavailable_text(reason: str) -> str:
    reason = reason.strip() or "状态未知"
    return f"机器人登录状态：{reason}。"


def _short_notice_text(text: str, *, max_chars: int = 120) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = " ".join(lines) if lines else text.strip()
    if len(summary) <= max_chars:
        return summary
    return f"{summary[:max_chars]}..."


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


def _clean_notice_text(text: str) -> str:
    cleaned = HTML_TAG_PATTERN.sub("", text)
    return cleaned.replace("\\n", "\n").strip()


def _format_datetime(value: datetime) -> str:
    return value.strftime("%m-%d %H:%M")


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)
