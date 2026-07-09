# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from nonebot.log import logger

from .models import ActivityInfo
from .offer_notice import offer_blocks, offer_end_time, offer_window_from_blocks
from .planning import activity_sort_end_time

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from typing import Any

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def parse_datetime(value: Any) -> datetime | None:
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


def build_active_activity_infos(
    rows: Iterable[Mapping[str, Any]],
    now: datetime,
) -> list[ActivityInfo]:
    activities: list[ActivityInfo] = []
    for row in rows:
        end_time = parse_datetime(row.get("end_time"))
        if end_time is None or end_time <= now:
            continue

        start_time = parse_datetime(row.get("start_time"))
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

    return sorted(
        activities,
        key=lambda activity: (
            activity_sort_end_time(activity),
            activity.sort_order,
            activity.activity_id,
        ),
    )
