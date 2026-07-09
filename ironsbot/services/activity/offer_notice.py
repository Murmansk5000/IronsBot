# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .notice_source import fetch_unity_notice_text

if TYPE_CHECKING:
    from .models import ActivityInfo

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
NOTICE_ACTIVITY_BLOCK_CHARS = 900
NOTICE_ACTIVITY_LOOKBEHIND_CHARS = 80
DAYS_PER_WEEK = 7
DEFAULT_OFFER_WINDOW_WEEKS = 1
HOURS_PER_DAY = 24
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


def offer_blocks(activity: ActivityInfo, now: datetime) -> list[str]:
    if activity.start_time is None:
        return []

    notice_text = fetch_unity_notice_text(now)
    if not notice_text:
        return []
    if activity.name not in notice_text:
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


def _parse_week_count(text_value: str | None) -> int | None:
    if text_value is None:
        return 1
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
        hour = HOURS_PER_DAY if hour_text == "24" else int(hour_text)
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
        r"(?P<label>(?:首|第(?P<count>\d+|[一二两三四五六七八九十])个?)周)",
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
        r"(?P<label>(?:首|第(?P<count>\d+|[一二两三四五六七八九十])个?)天)",
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
        r"(?P<label>(?:首|第(?P<count>\d+|[一二两三四五六七八九十])个?)月)",
        block,
    )
    if month_match is not None:
        month_count = _parse_week_count(month_match.group("count"))
        if month_count is not None and month_count > 0:
            return f"{month_match.group('label')}优惠", month_count * 30

    if "首月" in block or "第一月" in block:
        return "首月优惠", 30

    return None


def offer_window_from_blocks(blocks: list[str]) -> tuple[str, int] | None:
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
        r"(?P<month>\d{1,2})[.月](?P<day>\d{1,2})[日号]?"
        r"\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{1,2})"
        r"(?::(?P<second>\d{1,2}))?",
        block,
    )
    if match is not None:
        return _datetime_from_match(match, activity, default_hour=0)

    match = re.search(
        r"截止至\s*(?:(?P<year>\d{4})[.年])?"
        r"(?P<month>\d{1,2})[.月](?P<day>\d{1,2})[日号]?"
        r"\s*(?P<hour>\d{1,2}|24)点?"
        r"(?:(?P<minute>\d{1,2})分)?",
        block,
    )
    if match is not None:
        return _datetime_from_match(match, activity, default_hour=0)

    match = re.search(
        r"(?:(?P<year>\d{4})[.年])?"
        r"(?P<month>\d{1,2})[.月](?P<day>\d{1,2})[日号]?"
        r"\s*(?P<hour>\d{1,2}|24)?点?(?:价格)?(?:恢复|回复)",
        block,
    )
    if match is not None:
        return _datetime_from_match(match, activity, default_hour=0)

    match = re.search(
        r"(?:(?P<year>\d{4})[.年])?"
        r"(?P<month>\d{1,2})[.月](?P<day>\d{1,2})[日号]?"
        r"\s*(?:更新前|更新后(?:价格)?(?:恢复|回复))",
        block,
    )
    if match is not None:
        return _datetime_from_match(match, activity, default_hour=10)

    match = re.search(
        r"(?:购买时间|生效时间|限时生效|活动时间)[：:\s]*"
        r"(?:(?P<start_year>\d{4})[.年])?"
        r"\d{1,2}月\d{1,2}日?(?:更新前)?[-~至到]+"
        r"(?:(?P<year>\d{4})[.年])?"
        r"(?P<month>\d{1,2})[.月](?P<day>\d{1,2})[日号]?"
        r"(?:(?P<hour>\d{1,2}|24)点?)?(?:更新前)?",
        block,
    )
    if match is not None:
        return _datetime_from_match(match, activity, default_hour=10)

    return None


def offer_end_time(
    activity: ActivityInfo,
    blocks: list[str],
) -> datetime | None:
    for block in blocks:
        end_time = _parse_offer_deadline_with_hour(block, activity)
        if end_time is not None and end_time < activity.end_time:
            return end_time
    return None
