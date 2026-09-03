# SPDX-License-Identifier: MIT
from datetime import datetime, timedelta, timezone

TZ_CN = timezone(timedelta(hours=8))


def now(tz: timezone | None = None) -> datetime:
    if tz is None:
        return datetime.now(timezone.utc).astimezone()
    return datetime.now(tz=tz)


def set_timezone(dt: datetime, tz: timezone) -> datetime:
    if tz is None:
        return dt.astimezone()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(tz=tz)
    return dt.astimezone(tz=tz)


__all__ = [
    "TZ_CN",
    "now",
    "set_timezone",
]
