# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from ironsbot.core.commands import positive_int_list

from .catalog import build_active_activity_infos
from .delivery import (
    ActivityReminderDelivery,
    ActivityReminderTargets,
    build_reminder_delivery,
    filter_reminders_before_send,
)
from .formatting import format_activity_line
from .planning import (
    activity_deadline,
    activity_is_soon_ending,
    activity_sort_end_time,
    build_scheduled_reminders,
)
from .scheduler import register_scan_jobs, replace_reminder_jobs

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping

    from ironsbot.config.models.activity import ActivityConfig

    from .models import ActivityInfo, ActivityInfoCache, ActivityReminder

ACTIVITY_PUSH_SUBSCRIPTION_KEY = "seer_activity_push"
EMPTY_CURRENT_ACTIVITY_MESSAGE = "📭 当前没有从活动中心读到正在进行的活动。"
EMPTY_NEW_ACTIVITY_MESSAGE = "📭 本周没有比上周新增的活动。"
NEW_ACTIVITY_SNAPSHOT_UNAVAILABLE_MESSAGE = (
    "📭 暂无上周活动快照，暂时无法判断本周新增活动。"
)
EMPTY_SOON_ENDING_ACTIVITY_MESSAGE = "📭 当前没有读到不足 7 天结束的活动。"
REMINDER_DISPATCH_TOLERANCE = timedelta(minutes=1)
TargetType = Literal["group", "private"]
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActivityService:
    config: ActivityConfig
    cache: ActivityInfoCache
    load_rows: Callable[[], list[Mapping[str, Any]]]
    load_notice_text: Callable[[datetime], Awaitable[str]]
    cache_ttl: timedelta
    soon_ending_threshold: timedelta
    filter_unsent: Callable[[list[ActivityReminder]], list[ActivityReminder]]
    mark_sent: Callable[[list[ActivityReminder], datetime], None]
    preference_values: Callable[[], Iterable[str]]
    preference_for_target: Callable[[TargetType, int], str | None]
    targets: Callable[[], ActivityReminderTargets]
    broadcast: Callable[[ActivityReminderDelivery], Awaitable[bool]]
    newly_observed_activity_ids: Callable[
        [set[int], datetime], tuple[frozenset[int], bool]
    ]
    now: Callable[[], datetime]

    async def active_activity_infos(self, now: datetime) -> list[ActivityInfo]:
        if self.cache.expires_at is not None and self.cache.expires_at > now:
            return [
                activity
                for activity in self.cache.items
                if activity.end_time > now
                and (
                    activity.start_time is None
                    or activity.start_time <= now
                )
            ]

        rows, notice_text = await asyncio.gather(
            asyncio.to_thread(self.load_rows),
            self.load_notice_text(now),
        )
        new_activity_ids, has_previous_week_snapshot = (
            self.newly_observed_activity_ids(
                {
                    int(row["id"])
                    for row in rows
                    if row.get("id") is not None
                },
                now,
            )
        )
        activities = build_active_activity_infos(
            rows,
            now,
            notice_text=notice_text,
        )
        self.cache.items = activities
        self.cache.expires_at = now + self.cache_ttl
        self.cache.new_activity_ids = new_activity_ids
        self.cache.has_previous_week_snapshot = has_previous_week_snapshot
        return list(activities)

    async def soon_ending_activity_infos(
        self,
        now: datetime,
    ) -> list[ActivityInfo]:
        activities = [
            activity
            for activity in await self.active_activity_infos(now)
            if activity_is_soon_ending(
                activity,
                now,
                soon_ending_threshold=self.soon_ending_threshold,
            )
        ]
        return sorted(
            activities,
            key=lambda activity: (
                activity_sort_end_time(
                    activity,
                    now,
                    soon_ending_threshold=self.soon_ending_threshold,
                ),
                activity.sort_order,
                activity.activity_id,
            ),
        )

    async def newly_added_activity_infos(
        self,
        now: datetime,
    ) -> tuple[list[ActivityInfo], bool]:
        activities = await self.active_activity_infos(now)
        return (
            [
                activity
                for activity in activities
                if activity.activity_id in self.cache.new_activity_ids
            ],
            self.cache.has_previous_week_snapshot,
        )

    async def build_current_message(
        self,
        *,
        limit: int | None = None,
        soon_only: bool = False,
    ) -> str:
        now = self.now()
        activities = (
            await self.soon_ending_activity_infos(now)
            if soon_only
            else await self.active_activity_infos(now)
        )
        if not activities:
            return (
                EMPTY_SOON_ENDING_ACTIVITY_MESSAGE
                if soon_only
                else EMPTY_CURRENT_ACTIVITY_MESSAGE
            )

        shown = activities if limit is None else activities[:limit]
        title = "快结束活动" if soon_only else "当前活动"
        lines = [f"📅【{title}】", f"截至 {now:%Y-%m-%d %H:%M}", ""]
        for index, activity in enumerate(shown, start=1):
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
                            soon_ending_threshold=self.soon_ending_threshold,
                        )
                        if soon_only
                        else None
                    ),
                )
            )

        hidden_count = len(activities) - len(shown)
        if limit is not None and hidden_count > 0:
            lines.append(f"...还有 {hidden_count} 个活动未显示")
        return "\n".join(lines)

    async def build_newly_added_message(
        self,
        *,
        limit: int | None = None,
    ) -> str:
        now = self.now()
        activities, has_previous_week_snapshot = await self.newly_added_activity_infos(
            now
        )
        if not has_previous_week_snapshot:
            return NEW_ACTIVITY_SNAPSHOT_UNAVAILABLE_MESSAGE
        if not activities:
            return EMPTY_NEW_ACTIVITY_MESSAGE

        shown = activities if limit is None else activities[:limit]
        lines = ["📅【新增活动】", f"截至 {now:%Y-%m-%d %H:%M}", ""]
        for index, activity in enumerate(shown, start=1):
            lines.extend(
                format_activity_line(
                    index,
                    activity,
                    now,
                    soon_only=False,
                )
            )

        hidden_count = len(activities) - len(shown)
        if limit is not None and hidden_count > 0:
            lines.append(f"...还有 {hidden_count} 个活动未显示")
        return "\n".join(lines)

    async def send_reminder(
        self,
        *,
        lead_hours: int,
        reminders: list[ActivityReminder],
    ) -> None:
        now = self.now()
        valid = filter_reminders_before_send(
            reminders,
            now=now,
            current_activities=await self.soon_ending_activity_infos(now),
            dispatch_tolerance=REMINDER_DISPATCH_TOLERANCE,
            soon_ending_threshold=self.soon_ending_threshold,
        )
        if not valid:
            _LOGGER.info(
                "activity ending reminder %sh skipped: no valid reminders",
                lead_hours,
            )
            return

        delivery = build_reminder_delivery(
            lead_hours,
            valid,
            self._targets_for_lead(lead_hours),
            template=self.config.message,
        )
        if delivery.status == "skip_no_targets":
            _LOGGER.warning("activity reminder skipped: no target groups or users")
            return
        if await self.broadcast(delivery):
            self.mark_sent(valid, now)

    async def schedule_reminders(self, scheduler: Any) -> None:
        if not self.config.enabled:
            return

        try:
            now = self.now()
            reminders = self.filter_unsent(
                build_scheduled_reminders(
                    await self.soon_ending_activity_infos(now),
                    now,
                    lead_hours=self._configured_lead_hours(),
                    grace=timedelta(minutes=self.config.grace_minutes),
                    soon_ending_threshold=self.soon_ending_threshold,
                )
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("activity reminder scan failed", exc_info=True)
            return

        if not reminders:
            _LOGGER.info("activity reminder scan found no pending reminders")
            return

        scheduled_count = replace_reminder_jobs(
            scheduler,
            self.send_reminder,
            reminders,
            grace_minutes=self.config.grace_minutes,
        )
        _LOGGER.info(
            "activity reminder scheduled %s pending reminders",
            scheduled_count,
        )

    def register_jobs(self, scheduler: Any) -> None:
        register_scan_jobs(
            scheduler,
            partial(self.schedule_reminders, scheduler),
            enabled=self.config.enabled,
            now=self.now(),
        )

    def _configured_lead_hours(self) -> list[int]:
        lead_hours = set(self.config.lead_hours)
        for value in self.preference_values():
            lead_hours.update(positive_int_list(value))
        return sorted(lead_hours, reverse=True)

    def _targets_for_lead(self, lead_hours: int) -> ActivityReminderTargets:
        def effective(target_type: TargetType, target_id: int) -> list[int]:
            preference = self.preference_for_target(target_type, target_id)
            if preference is None:
                return self.config.lead_hours
            return positive_int_list(preference) or self.config.lead_hours

        targets = self.targets()
        return ActivityReminderTargets(
            group_ids=tuple(
                group_id
                for group_id in targets.group_ids
                if lead_hours in effective("group", group_id)
            ),
            private_user_ids=tuple(
                user_id
                for user_id in targets.private_user_ids
                if lead_hours in effective("private", user_id)
            ),
        )
