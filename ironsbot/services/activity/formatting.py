# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from .models import ActivityDeadline, ActivityInfo, ActivityReminder

SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
MINUTES_PER_DAY = HOURS_PER_DAY * MINUTES_PER_HOUR


def format_remaining_time(delta: timedelta) -> str:
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


def format_activity_period(activity: ActivityInfo) -> str:
    end_text = f"{activity.end_time:%m-%d %H:%M}"
    if activity.start_time is None:
        return f"结束：{end_text}"
    return f"{activity.start_time:%m-%d %H:%M} ~ {end_text}"


def format_deadline_label(label: str) -> str:
    return label if label.endswith("时间") else f"{label}时间"


def format_activity_line(
    index: int,
    activity: ActivityInfo,
    current_time: datetime,
    *,
    soon_only: bool,
    deadline: ActivityDeadline | None = None,
) -> list[str]:
    if soon_only:
        if deadline is not None and deadline.display_end_time:
            remaining_text = format_remaining_time(deadline.end_time - current_time)
            deadline_label = format_deadline_label(deadline.label)
            return [
                (
                    f"{index}. {activity.name}：{deadline_label}："
                    f"{deadline.end_time:%m-%d %H:%M} | 剩余：{remaining_text}"
                )
            ]

        period_text = format_activity_period(activity)
        offer_label = activity.offer_label or "限时优惠"
        return [
            (
                f"{index}. {activity.name}：{offer_label}见官方说明 | "
                f"活动：{period_text}"
            )
        ]

    period_text = format_activity_period(activity)
    remaining_text = format_remaining_time(activity.end_time - current_time)
    return [
        f"{index}. {activity.name}：{period_text} | 剩余：{remaining_text}",
    ]


def format_activity_list(reminders: list[ActivityReminder]) -> str:
    lines: list[str] = []
    for index, reminder in enumerate(reminders, start=1):
        if reminder.display_end_time:
            deadline_label = format_deadline_label(reminder.end_label)
            lines.append(
                f"{index}. {reminder.name}：{deadline_label}："
                f"{reminder.end_time:%Y-%m-%d %H:%M}"
            )
        else:
            lines.append(
                f"{index}. {reminder.name}：{reminder.end_label}见官方说明"
            )
    return "\n".join(lines)
