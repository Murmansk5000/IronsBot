# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.log import logger

from .formatting import format_activity_list
from .planning import filter_valid_reminders

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime, timedelta

    from .models import ActivityInfo, ActivityReminder

DEFAULT_MESSAGE_TEMPLATE = "⏰ 本周活动将在约 {lead_hours} 小时后结束\n{activity_list}"


def format_reminder_message(
    lead_hours: int,
    reminders: list[ActivityReminder],
    *,
    template: str,
    fallback_template: str = DEFAULT_MESSAGE_TEMPLATE,
) -> str:
    try:
        return template.format(
            lead_hours=lead_hours,
            activity_count=len(reminders),
            activity_list=format_activity_list(reminders),
        )
    except (KeyError, IndexError, ValueError) as e:
        logger.warning(f"activity reminder template failed: {e}")
        return fallback_template.format(
            lead_hours=lead_hours,
            activity_list=format_activity_list(reminders),
        )


def filter_reminders_before_send(
    reminders: Iterable[ActivityReminder],
    *,
    now: datetime,
    current_activities: Iterable[ActivityInfo],
    dispatch_tolerance: timedelta,
    soon_ending_threshold: timedelta,
) -> list[ActivityReminder]:
    activity_by_id = {
        activity.activity_id: activity
        for activity in current_activities
    }
    return filter_valid_reminders(
        reminders,
        now=now,
        activity_by_id=activity_by_id,
        dispatch_tolerance=dispatch_tolerance,
        soon_ending_threshold=soon_ending_threshold,
    )
