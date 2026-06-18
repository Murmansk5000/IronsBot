# SPDX-License-Identifier: MIT
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from .models import ActivityDeadline, ActivityReminder

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from .models import ActivityInfo


def fallback_offer_window_end(activity: ActivityInfo) -> datetime | None:
    if (
        activity.offer_label is None
        or activity.offer_window_days is None
        or activity.start_time is None
    ):
        return None
    return activity.start_time + timedelta(days=activity.offer_window_days)


def activity_deadline(
    activity: ActivityInfo,
    now: datetime,
    *,
    soon_ending_threshold: timedelta,
) -> ActivityDeadline | None:
    fallback_end = fallback_offer_window_end(activity)

    if activity.offer_end_time is not None:
        if fallback_end is not None and fallback_end > activity.offer_end_time:
            if fallback_end >= now:
                return ActivityDeadline(
                    end_time=fallback_end,
                    label=activity.offer_label or "限时优惠",
                    display_end_time=False,
                )
        elif activity.offer_end_time >= now:
            return ActivityDeadline(
                end_time=activity.offer_end_time,
                label=f"{activity.offer_label or '限时优惠'}截至",
                display_end_time=True,
            )

    if (
        fallback_end is not None
        and activity.start_time is not None
        and activity.start_time <= now <= fallback_end
    ):
        return ActivityDeadline(
            end_time=fallback_end,
            label=activity.offer_label or "限时优惠",
            display_end_time=False,
        )

    if now < activity.end_time and activity.end_time - now < soon_ending_threshold:
        return ActivityDeadline(
            end_time=activity.end_time,
            label="结束时间",
            display_end_time=True,
        )

    return None


def activity_is_soon_ending(
    activity: ActivityInfo,
    now: datetime,
    *,
    soon_ending_threshold: timedelta,
) -> bool:
    return (
        activity_deadline(
            activity,
            now,
            soon_ending_threshold=soon_ending_threshold,
        )
        is not None
    )


def activity_sort_end_time(
    activity: ActivityInfo,
    now: datetime | None = None,
    *,
    soon_ending_threshold: timedelta | None = None,
) -> datetime:
    if now is not None and soon_ending_threshold is not None:
        deadline = activity_deadline(
            activity,
            now,
            soon_ending_threshold=soon_ending_threshold,
        )
        if deadline is not None:
            return deadline.end_time
    return activity.offer_end_time or activity.end_time


def effective_reminder_send_time(
    planned_send_time: datetime,
    now: datetime,
    *,
    grace: timedelta,
) -> datetime | None:
    if planned_send_time >= now:
        return planned_send_time

    if now <= planned_send_time + grace:
        return now

    return None


def build_scheduled_reminders(
    activities: Iterable[ActivityInfo],
    now: datetime,
    *,
    lead_hours: Iterable[int],
    grace: timedelta,
    soon_ending_threshold: timedelta,
) -> list[ActivityReminder]:
    reminders: list[ActivityReminder] = []

    for activity in activities:
        deadline = activity_deadline(
            activity,
            now,
            soon_ending_threshold=soon_ending_threshold,
        )
        if deadline is None:
            continue

        for lead_hour in lead_hours:
            planned_send_time = deadline.end_time - timedelta(hours=lead_hour)
            send_time = effective_reminder_send_time(
                planned_send_time,
                now,
                grace=grace,
            )
            if send_time is None:
                continue

            reminders.append(
                ActivityReminder(
                    activity_id=activity.activity_id,
                    name=activity.name,
                    end_time=deadline.end_time,
                    lead_hours=lead_hour,
                    send_time=send_time,
                    end_label=deadline.label,
                    display_end_time=deadline.display_end_time,
                )
            )

    return reminders


def reminder_key(reminder: ActivityReminder) -> tuple[int, str, int]:
    return (
        reminder.activity_id,
        reminder.end_time.isoformat(),
        reminder.lead_hours,
    )


def group_by_send_time(
    reminders: Iterable[ActivityReminder],
) -> dict[tuple[int, datetime], list[ActivityReminder]]:
    grouped: dict[tuple[int, datetime], list[ActivityReminder]] = {}
    for reminder in reminders:
        grouped.setdefault((reminder.lead_hours, reminder.send_time), []).append(
            reminder
        )
    return grouped


def is_reminder_still_valid(
    reminder: ActivityReminder,
    *,
    now: datetime,
    activity_by_id: dict[int, ActivityInfo],
    dispatch_tolerance: timedelta,
    soon_ending_threshold: timedelta,
) -> bool:
    if now > reminder.send_time + dispatch_tolerance:
        return False

    current_activity = activity_by_id.get(reminder.activity_id)
    if current_activity is None:
        return False

    deadline = activity_deadline(
        current_activity,
        now,
        soon_ending_threshold=soon_ending_threshold,
    )
    if deadline is None:
        return False
    return (
        deadline.end_time == reminder.end_time
        and deadline.display_end_time == reminder.display_end_time
    )


def filter_valid_reminders(
    reminders: Iterable[ActivityReminder],
    *,
    now: datetime,
    activity_by_id: dict[int, ActivityInfo],
    dispatch_tolerance: timedelta,
    soon_ending_threshold: timedelta,
) -> list[ActivityReminder]:
    return [
        reminder
        for reminder in reminders
        if is_reminder_still_valid(
            reminder,
            now=now,
            activity_by_id=activity_by_id,
            dispatch_tolerance=dispatch_tolerance,
            soon_ending_threshold=soon_ending_threshold,
        )
    ]
