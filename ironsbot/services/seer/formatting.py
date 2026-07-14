# SPDX-License-Identifier: GPL-3.0-or-later
from datetime import datetime, timedelta, timezone


def yes_no(value: object) -> str:
    return "是" if bool(value) else "否"


def format_datetime(timestamp: int) -> str:
    if timestamp <= 0:
        return "未知"

    dt = datetime.fromtimestamp(timestamp, tz=timezone(timedelta(hours=8)))
    return (
        f"{dt.year}年{dt.month}月{dt.day}日 "
        f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"
    )
