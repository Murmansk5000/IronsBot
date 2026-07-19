# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

from ironsbot.core.messaging import MessageTarget
from ironsbot.services.operations.scheduler import JobRegistry

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import TeamAuditWelcomeConfig
    from ironsbot.core.features import FeatureService
    from ironsbot.services.messaging.delivery import MessageDelivery
    from ironsbot.services.operations.scheduler import Scheduler

logger = logging.getLogger(__name__)

TEAM_AUDIT_FEATURE = "team_audit"
TEAM_AUDIT_JOB_PREFIX = "team_audit_followup_"
FOLLOWUP_SCAN_INTERVAL_MINUTES = 10
FIRST_FOLLOWUP_STEP = 1
FINAL_FOLLOWUP_STEP = 2


class TeamAuditPendingReminder(NamedTuple):
    group_id: int
    user_id: int
    joined_at: datetime
    remind_at: datetime
    step: int = FIRST_FOLLOWUP_STEP


class TeamAuditReminderStore(Protocol):
    def save(self, reminder: TeamAuditPendingReminder) -> None: ...

    def get(self, group_id: int, user_id: int) -> TeamAuditPendingReminder | None: ...

    def list_all(self) -> list[TeamAuditPendingReminder]: ...

    def clear(self, group_id: int, user_id: int) -> None: ...


class TeamAuditGroupProbe(Protocol):
    async def can_access(self, bot: Any, *, group_id: int) -> bool: ...

    async def has_member(
        self,
        bot: Any,
        *,
        group_id: int,
        user_id: int,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class TeamAuditService:
    _config: TeamAuditWelcomeConfig
    _store: TeamAuditReminderStore
    _features: FeatureService
    _delivery: MessageDelivery
    _group_probe: TeamAuditGroupProbe

    def active_for_group(self, group_id: int) -> bool:
        return self._config.enabled and self._features.group_has_feature(
            group_id,
            TEAM_AUDIT_FEATURE,
        )

    async def welcome(
        self,
        *,
        group_id: int,
        user_id: int,
        joined_at: datetime,
        scheduler: Scheduler,
        bot: Any,
    ) -> None:
        if not self.active_for_group(group_id):
            return
        await self._delivery.send_targets(
            [MessageTarget("group", group_id, (user_id,))],
            self._config.message,
            bot=bot,
            action_name="team audit welcome",
            interval_seconds=0,
        )
        if not self._config.followup_enabled:
            return
        reminder = self._record(
            group_id=group_id,
            user_id=user_id,
            joined_at=joined_at,
            delay_hours=self._config.followup_after_hours,
        )
        self.schedule(scheduler, reminder)

    async def start(self, _bot: Any, *, scheduler: Scheduler) -> None:
        await self.schedule_pending(scheduler)
        JobRegistry(scheduler, prefix=TEAM_AUDIT_JOB_PREFIX).add(
            self.schedule_pending,
            "interval",
            minutes=FOLLOWUP_SCAN_INTERVAL_MINUTES,
            args=[scheduler],
            job_id="scan",
        )

    async def schedule_pending(self, scheduler: Scheduler) -> None:
        if not self._followup_enabled:
            return
        for reminder in self._store.list_all():
            self.schedule(scheduler, reminder)

    def schedule(
        self,
        scheduler: Scheduler,
        reminder: TeamAuditPendingReminder,
        *,
        now: datetime | None = None,
    ) -> None:
        if not self._followup_enabled:
            return
        current = now or datetime.now(timezone.utc)
        run_at = reminder.remind_at
        if run_at <= current:
            run_at = current + timedelta(seconds=1)
        JobRegistry(scheduler, prefix=TEAM_AUDIT_JOB_PREFIX).add(
            self.send_followup,
            "date",
            run_date=run_at,
            args=[reminder.group_id, reminder.user_id],
            kwargs={"scheduler": scheduler},
            job_id=f"{reminder.group_id}_{reminder.user_id}",
            misfire_grace_time=3600,
        )

    async def send_followup(
        self,
        group_id: int,
        user_id: int,
        *,
        scheduler: Scheduler,
    ) -> None:
        reminder = self._pending_reminder(group_id, user_id)
        if reminder is None:
            return

        target = MessageTarget("group", group_id, (user_id,))
        bot = self._delivery.bot_for_target(target)
        if bot is None:
            logger.warning(
                "team audit followup skipped: no connected bot for "
                "group=%s user=%s",
                group_id,
                user_id,
            )
            return
        if not await self._group_probe.can_access(bot, group_id=group_id):
            return
        if not await self._group_probe.has_member(
            bot,
            group_id=group_id,
            user_id=user_id,
        ):
            self._store.clear(group_id, user_id)
            return

        summary = await self._delivery.send_targets(
            [target],
            self._followup_message(reminder),
            bot=bot,
            action_name="team audit followup",
            interval_seconds=0,
        )
        if not summary.succeeded:
            logger.warning(
                "team audit followup send failed: group=%s user=%s bot_self_id=%s",
                group_id,
                user_id,
                getattr(bot, "self_id", "unknown"),
            )
            return
        self._finish_followup(scheduler, reminder)

    def _pending_reminder(
        self,
        group_id: int,
        user_id: int,
    ) -> TeamAuditPendingReminder | None:
        if not self._followup_enabled:
            return None
        reminder = self._store.get(group_id, user_id)
        if reminder is None:
            return None
        final_disabled = (
            reminder.step >= FINAL_FOLLOWUP_STEP
            and not self._config.final_followup_enabled
        )
        if final_disabled or not self.active_for_group(group_id):
            self._store.clear(group_id, user_id)
            return None
        return reminder

    @property
    def _followup_enabled(self) -> bool:
        return self._config.enabled and self._config.followup_enabled

    def _record(
        self,
        *,
        group_id: int,
        user_id: int,
        joined_at: datetime,
        delay_hours: float,
        step: int = FIRST_FOLLOWUP_STEP,
    ) -> TeamAuditPendingReminder:
        joined_at = _as_utc(joined_at)
        reminder = TeamAuditPendingReminder(
            group_id,
            user_id,
            joined_at,
            joined_at + timedelta(hours=delay_hours),
            max(FIRST_FOLLOWUP_STEP, int(step)),
        )
        self._store.save(reminder)
        return reminder

    def _finish_followup(
        self,
        scheduler: Scheduler,
        reminder: TeamAuditPendingReminder,
    ) -> None:
        if (
            reminder.step < FINAL_FOLLOWUP_STEP
            and self._config.final_followup_enabled
        ):
            final_reminder = self._record(
                group_id=reminder.group_id,
                user_id=reminder.user_id,
                joined_at=reminder.joined_at,
                delay_hours=self._config.final_followup_after_hours,
                step=FINAL_FOLLOWUP_STEP,
            )
            self.schedule(scheduler, final_reminder)
            return
        self._store.clear(reminder.group_id, reminder.user_id)

    def _followup_message(self, reminder: TeamAuditPendingReminder) -> str:
        final = reminder.step >= FINAL_FOLLOWUP_STEP
        template = (
            self._config.final_followup_message
            if final
            else self._config.followup_message
        )
        hours = (
            self._config.final_followup_after_hours
            if final
            else self._config.followup_after_hours
        )
        try:
            return template.format(
                hours=hours,
                group_id=reminder.group_id,
                user_id=reminder.user_id,
            )
        except (IndexError, KeyError, ValueError):
            return template


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
