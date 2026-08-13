# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import TYPE_CHECKING, NamedTuple, Protocol

from ironsbot.core.outbound import (
    MentionPart,
    OutboundMessage,
    OutboundMessenger,
    TextPart,
)
from ironsbot.services.operations.scheduler import JobRegistry

if TYPE_CHECKING:
    from ironsbot.config.models.messaging import TeamAuditWelcomeConfig
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.operations.scheduler import Scheduler

logger = logging.getLogger(__name__)

TEAM_AUDIT_FEATURE = "team_audit"
TEAM_AUDIT_JOB_PREFIX = "team_audit_followup_"
FOLLOWUP_SCAN_INTERVAL_MINUTES = 10
FIRST_FOLLOWUP_STEP = 1
FINAL_FOLLOWUP_STEP = 2


class TeamAuditPendingReminder(NamedTuple):
    conversation: ConversationRef
    actor: ActorRef
    joined_at: datetime
    remind_at: datetime
    step: int = FIRST_FOLLOWUP_STEP


class TeamAuditReminderStore(Protocol):
    def save(self, reminder: TeamAuditPendingReminder) -> None: ...

    def get(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
    ) -> TeamAuditPendingReminder | None: ...

    def list_all(self) -> list[TeamAuditPendingReminder]: ...

    def clear(self, conversation: ConversationRef, actor: ActorRef) -> None: ...


class TeamAuditPolicy(Protocol):
    def enabled_for(self, conversation: ConversationRef) -> bool: ...


class TeamAuditMembershipProbe(Protocol):
    async def can_access(self, conversation: ConversationRef) -> bool: ...

    async def has_member(
        self,
        conversation: ConversationRef,
        *,
        actor: ActorRef,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class TeamAuditService:
    _config: TeamAuditWelcomeConfig
    _store: TeamAuditReminderStore
    _policy: TeamAuditPolicy
    _messenger: OutboundMessenger
    _membership_probe: TeamAuditMembershipProbe

    def active_for(self, conversation: ConversationRef) -> bool:
        return self._config.enabled and self._policy.enabled_for(conversation)

    async def welcome(
        self,
        *,
        conversation: ConversationRef,
        actor: ActorRef,
        joined_at: datetime,
        scheduler: Scheduler,
    ) -> None:
        if not self.active_for(conversation):
            return
        result = await self._messenger.send(
            conversation,
            OutboundMessage((MentionPart(actor), TextPart(self._config.message))),
        )
        if not result.delivered:
            logger.warning(
                "team audit welcome send failed: conversation=%s:%s actor=%s error=%s",
                conversation.kind,
                conversation.id,
                actor.id,
                result.error_code or result.error_message,
            )
        if not self._config.followup_enabled:
            return
        reminder = self._record(
            conversation=conversation,
            actor=actor,
            joined_at=joined_at,
            delay_hours=self._config.followup_after_hours,
        )
        self.schedule(scheduler, reminder)

    async def start(self, *, scheduler: Scheduler) -> None:
        await self.schedule_pending(scheduler)
        JobRegistry(scheduler, prefix=TEAM_AUDIT_JOB_PREFIX).add_wall_clock_interval(
            self.schedule_pending,
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
            args=[reminder.conversation, reminder.actor],
            kwargs={"scheduler": scheduler},
            job_id=_reminder_job_suffix(reminder),
            misfire_grace_time=3600,
        )

    async def send_followup(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
        *,
        scheduler: Scheduler,
    ) -> None:
        reminder = self._pending_reminder(conversation, actor)
        if reminder is None:
            return

        if not await self._membership_probe.can_access(conversation):
            return
        if not await self._membership_probe.has_member(conversation, actor=actor):
            self._store.clear(conversation, actor)
            return

        result = await self._messenger.send(
            conversation,
            OutboundMessage(
                (MentionPart(actor), TextPart(self._followup_message(reminder)))
            ),
        )
        if not result.delivered:
            logger.warning(
                "team audit followup send failed: conversation=%s:%s actor=%s error=%s",
                conversation.kind,
                conversation.id,
                actor.id,
                result.error_code or result.error_message,
            )
            return
        self._finish_followup(scheduler, reminder)

    def _pending_reminder(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
    ) -> TeamAuditPendingReminder | None:
        if not self._followup_enabled:
            return None
        reminder = self._store.get(conversation, actor)
        if reminder is None:
            return None
        final_disabled = (
            reminder.step >= FINAL_FOLLOWUP_STEP
            and not self._config.final_followup_enabled
        )
        if final_disabled or not self.active_for(conversation):
            self._store.clear(conversation, actor)
            return None
        return reminder

    @property
    def _followup_enabled(self) -> bool:
        return self._config.enabled and self._config.followup_enabled

    def _record(
        self,
        *,
        conversation: ConversationRef,
        actor: ActorRef,
        joined_at: datetime,
        delay_hours: float,
        step: int = FIRST_FOLLOWUP_STEP,
    ) -> TeamAuditPendingReminder:
        joined_at = _as_utc(joined_at)
        reminder = TeamAuditPendingReminder(
            conversation,
            actor,
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
        if reminder.step < FINAL_FOLLOWUP_STEP and self._config.final_followup_enabled:
            final_reminder = self._record(
                conversation=reminder.conversation,
                actor=reminder.actor,
                joined_at=reminder.joined_at,
                delay_hours=self._config.final_followup_after_hours,
                step=FINAL_FOLLOWUP_STEP,
            )
            self.schedule(scheduler, final_reminder)
            return
        self._store.clear(reminder.conversation, reminder.actor)

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
                group_id=reminder.conversation.id,
                user_id=reminder.actor.id,
            )
        except (IndexError, KeyError, ValueError):
            return template


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _reminder_job_suffix(reminder: TeamAuditPendingReminder) -> str:
    """Generate a scheduler-safe key without encoding platform IDs in job names."""

    key = "\x1f".join(
        (
            reminder.conversation.platform.value,
            reminder.conversation.kind,
            reminder.conversation.id,
            reminder.actor.platform.value,
            reminder.actor.kind,
            reminder.actor.id,
            reminder.actor.scope_id or "",
        )
    )
    return sha256(key.encode("utf-8")).hexdigest()[:24]
