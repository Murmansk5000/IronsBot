# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime, timedelta, timezone

PEAK_RATING_NAMES = ("学徒", "猛将", "天骄", "王者", "圣皇", "宇宙圣皇")


def yes_no(value: object) -> str:
    return "是" if bool(value) else "否"


def format_datetime(timestamp: int) -> str:
    if timestamp <= 0:
        return "未知"

    dt = datetime.fromtimestamp(timestamp, tz=timezone(timedelta(hours=8)))
    return f"{dt.year}年{dt.month}月{dt.day}日 {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def format_possible_datetime(value: int) -> str:
    if value <= 0:
        return "未知"

    if value < 946684800:
        return str(value)

    return f"{format_datetime(value)}（{value}）"


def format_peak_rating(data: int) -> str:
    rank = data & 0xFFFF
    if rank >= len(PEAK_RATING_NAMES):
        return "未知"

    return PEAK_RATING_NAMES[rank]


def format_peak_value(value: int) -> str:
    return f"{value}（段位：{format_peak_rating(value)}）"
