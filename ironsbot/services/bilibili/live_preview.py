# SPDX-License-Identifier: MIT
"""Conservative, publication-relative parsing of first-party live announcements."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ironsbot.core.time import TZ_CN
from ironsbot.services.bilibili.parser import (
    dynamic_content,
    dynamic_id,
    item_author_mid,
    item_pub_ts,
)

LIVE_PREVIEW_CATEGORY = "live_preview"
LIVE_REMINDER_PREFERENCE = "__live_reminder__"
SEER_LIVE_UID = 1310714247
LIVE_ALL_SUBSCRIPTION = "bili_all:live"
_HALF_DAY_HOURS = 12
_DECEMBER = 12
_MIDDAY_CUTOFF = 11
_CLOCK = re.compile(
    r"(?P<period>凌晨|早上|上午|中午|下午|傍晚|晚上|晚间|晚)?\s*"
    r"(?P<hour>\d{1,2}|[零一二两三四五六七八九十]{1,3})"
    r"(?:[:：](?P<minute>\d{2})|[点时](?P<half>半)?"
    r"(?P<cnminute>\d{1,2}|[零一二三四五六七八九十]{1,3})?分?)"
)
_DATE = re.compile(
    r"(?:(?P<year>20\d{2})年)?(?P<month>\d{1,2})月(?P<day>\d{1,2})[日号]?"
    r"|(?P<relative>今天|今日|今晚|明天|明日|明晚|后天|后日)"
    r"|(?P<week>本周|这周|下周|周|星期)(?P<weekday>[一二三四五六日天])"
)


@dataclass(frozen=True, slots=True)
class LivePreview:
    uid: int
    source_id: str
    published_at: float
    starts_at: float | None
    cancelled: bool = False
    rescheduled: bool = False


def live_subscription_key(uid: int) -> str:
    return f"bili_live:{uid}"


def _number(value: str) -> int:
    if value.isdecimal():
        return int(value)
    numbers = dict(
        zip("零一二两三四五六七八九", (0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9), strict=True)
    )
    if "十" in value:
        left, _, right = value.partition("十")
        return (numbers[left] if left else 1) * 10 + (numbers[right] if right else 0)
    return numbers[value]


def _clock_parts(clock: re.Match[str], *, evening: bool) -> tuple[int, int]:
    hour = _number(clock["hour"])
    minute = (
        int(clock["minute"])
        if clock["minute"]
        else (30 if clock["half"] else _number(clock["cnminute"] or "0"))
    )
    period = clock["period"] or ""
    if (
        evening or period in {"下午", "傍晚", "晚上", "晚间", "晚"}
    ) and 1 <= hour < _HALF_DAY_HOURS:
        hour += _HALF_DAY_HOURS
    elif period == "凌晨" and hour == _HALF_DAY_HOURS:
        hour = 0
    elif period == "中午" and 1 <= hour < _MIDDAY_CUTOFF:
        hour += _HALF_DAY_HOURS
    return hour, minute


def _calendar_day(date: re.Match[str], published: datetime) -> datetime:
    if date["month"]:
        year = int(date["year"] or published.year)
        month, day = int(date["month"]), int(date["day"])
        if not date["year"] and published.month == _DECEMBER and month == 1:
            year += 1
        return datetime(year, month, day, tzinfo=TZ_CN)
    if date["relative"]:
        relative = date["relative"]
        days = (
            2
            if relative in {"后天", "后日"}
            else int(relative in {"明天", "明日", "明晚"})
        )
    else:
        weekday = "一二三四五六日".index(date["weekday"].replace("天", "日"))
        days = weekday - published.weekday()
        if date["week"] == "下周":
            days += 7
        elif date["week"] in {"周", "星期"}:
            days %= 7
    return published + timedelta(days=days)


def _time_in_paragraph(text: str, published: datetime) -> set[float]:
    found: set[float] = set()
    for date in _DATE.finditer(text):
        tail = text[date.end() : date.end() + 50]
        clock = _CLOCK.search(tail)
        if clock is None:
            continue
        between = tail[: clock.start()]
        if not re.fullmatch(r"[\s,，早上下午中午凌晨晚间晨傍晚]*", between):
            continue
        try:
            hour, minute = _clock_parts(
                clock, evening="晚" in between or date["relative"] in {"今晚", "明晚"}
            )
            scheduled = _calendar_day(date, published).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if scheduled >= published:
                found.add(scheduled.timestamp())
        except (KeyError, ValueError, OverflowError):
            continue
    return found


def parse_live_preview(item: dict[str, Any]) -> LivePreview | None:
    uid = item_author_mid(item)
    if item.get("orig") or item.get("type") == "DYNAMIC_TYPE_FORWARD":
        original = item.get("orig")
        if (
            not isinstance(original, dict)
            or uid <= 0
            or item_author_mid(original) != uid
        ):
            return None
    text = dynamic_content(item)
    if "直播" not in text or re.search(
        r"直播回放|录播|转播|(?:他人|别人|他们|她们|他|她).{0,12}直播"
        r"|版本更新指引|本周主打精灵",
        text,
    ):
        return None
    if not re.search(
        r"预告|即将|定档|开启|开播|不见不散|直播时间|今晚|明晚|取消|暂停", text
    ):
        return None
    pub_ts, source = item_pub_ts(item), dynamic_id(item)
    if not uid or not pub_ts or not source:
        return None
    try:
        published = datetime.fromtimestamp(pub_ts, TZ_CN)
    except (ValueError, OverflowError, OSError):
        return None
    cancelled = bool(
        re.search(
            r"(?:取消|暂停)(?:本次|今日|今晚|明晚|明天|的|这次|此次|本场)*直播"
            r"|直播(?:现已|将)?(?:取消|暂停)|不开播",
            text,
        )
    )
    changed = re.search(r"改为|改至|改到|调整为|推迟至|延期至", text)
    timing_text = text[changed.end() :] if changed else text
    times: set[float] = set()
    for paragraph in re.split(r"\n\s*\n", timing_text):
        times.update(_time_in_paragraph(paragraph, published))
    return LivePreview(
        uid,
        source,
        pub_ts,
        next(iter(times)) if len(times) == 1 else None,
        cancelled,
        changed is not None,
    )
