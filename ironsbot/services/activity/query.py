# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .catalog import build_active_activity_infos
from .delivery import filter_reminders_before_send
from .formatting import format_activity_line
from .planning import (
    activity_deadline,
    activity_is_soon_ending,
    activity_sort_end_time,
    build_scheduled_reminders,
)

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from .models import ActivityInfo, ActivityInfoCache, ActivityReminder

LoadActivityRows = Callable[[], list[Mapping[str, Any]]]

EMPTY_CURRENT_ACTIVITY_MESSAGE = "📭 当前没有从活动中心读到正在进行的活动。"
EMPTY_SOON_ENDING_ACTIVITY_MESSAGE = "📭 当前没有读到不足 7 天结束的活动。"


@dataclass(frozen=True, slots=True)
class ActivityQuerySource:
    cache: ActivityInfoCache
    load_rows: LoadActivityRows
    cache_ttl: timedelta
    soon_ending_threshold: timedelta


def active_activity_infos(
    source: ActivityQuerySource,
    now: datetime,
) -> list[ActivityInfo]:
    if source.cache.expires_at is not None and source.cache.expires_at > now:
        return [
            activity
            for activity in source.cache.items
            if activity.end_time > now
            and (activity.start_time is None or activity.start_time <= now)
        ]

    sorted_activities = build_active_activity_infos(source.load_rows(), now)
    source.cache.items = sorted_activities
    source.cache.expires_at = now + source.cache_ttl
    return list(sorted_activities)


def soon_ending_activity_infos(
    source: ActivityQuerySource,
    now: datetime,
) -> list[ActivityInfo]:
    activities = [
        activity
        for activity in active_activity_infos(source, now)
        if activity_is_soon_ending(
            activity,
            now,
            soon_ending_threshold=source.soon_ending_threshold,
        )
    ]
    return sorted(
        activities,
        key=lambda activity: (
            activity_sort_end_time(
                activity,
                now,
                soon_ending_threshold=source.soon_ending_threshold,
            ),
            activity.sort_order,
            activity.activity_id,
        ),
    )


def build_activity_query_message(
    source: ActivityQuerySource,
    now: datetime,
    *,
    limit: int | None = None,
    soon_only: bool = False,
) -> str:
    activities = (
        soon_ending_activity_infos(source, now)
        if soon_only
        else active_activity_infos(source, now)
    )

    if not activities:
        return (
            EMPTY_SOON_ENDING_ACTIVITY_MESSAGE
            if soon_only
            else EMPTY_CURRENT_ACTIVITY_MESSAGE
        )

    shown_activities = activities if limit is None else activities[:limit]
    title = "快结束活动" if soon_only else "当前活动"
    lines = [
        f"📅【{title}】",
        f"截至 {now:%Y-%m-%d %H:%M}",
        "",
    ]

    for index, activity in enumerate(shown_activities, start=1):
        lines.extend(
            format_activity_line(
                index,
                activity,
                now,
                soon_only=soon_only,
                deadline=(
                    activity_deadline(
                        activity,
                        now,
                        soon_ending_threshold=source.soon_ending_threshold,
                    )
                    if soon_only
                    else None
                ),
            )
        )

    hidden_count = len(activities) - len(shown_activities)
    if limit is not None and hidden_count > 0:
        lines.append(f"...还有 {hidden_count} 个活动未显示")

    return "\n".join(lines)


def scheduled_reminders(
    source: ActivityQuerySource,
    now: datetime,
    *,
    lead_hours: Iterable[int],
    grace: timedelta,
) -> list[ActivityReminder]:
    return build_scheduled_reminders(
        soon_ending_activity_infos(source, now),
        now,
        lead_hours=lead_hours,
        grace=grace,
        soon_ending_threshold=source.soon_ending_threshold,
    )


def valid_reminders_before_send(
    source: ActivityQuerySource,
    reminders: Iterable[ActivityReminder],
    *,
    now: datetime,
    dispatch_tolerance: timedelta,
) -> list[ActivityReminder]:
    return filter_reminders_before_send(
        reminders,
        now=now,
        current_activities=soon_ending_activity_infos(source, now),
        dispatch_tolerance=dispatch_tolerance,
        soon_ending_threshold=source.soon_ending_threshold,
    )
