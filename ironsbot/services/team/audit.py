# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import TYPE_CHECKING, NamedTuple, Protocol

from ironsbot.core.outbound import (
    MentionPart,
    OutboundMessage,
    OutboundMessenger,
    TextPart,
)
from ironsbot.core.platform import reference_digest
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
    async def save(self, reminder: TeamAuditPendingReminder) -> None: ...

    async def get(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
    ) -> TeamAuditPendingReminder | None: ...

    async def list_all(self) -> list[TeamAuditPendingReminder]: ...

    async def transition(
        self,
        expected: TeamAuditPendingReminder,
        *,
        replacement: TeamAuditPendingReminder | None = None,
    ) -> bool: ...


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


@dataclass(slots=True)
class TeamAuditService:
    _config: TeamAuditWelcomeConfig
    _store: TeamAuditReminderStore
    _policy: TeamAuditPolicy
    _messenger: OutboundMessenger
    _membership_probe: TeamAuditMembershipProbe
    _in_flight: set[tuple[ConversationRef, ActorRef]] = field(
        default_factory=set, init=False, repr=False, compare=False
    )
    _generation: object | None = field(
        default_factory=object, init=False, repr=False, compare=False
    )

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
        if self._generation is None or not self.active_for(conversation):
            return
        result = await self._messenger.send(
            conversation,
            OutboundMessage((MentionPart(actor), TextPart(self._config.message))),
        )
        if not result.delivered:
            logger.warning(
                "team audit welcome send failed: conversation=%s:%s actor=%s "
                "failure_kind=%s",
                conversation.kind,
                reference_digest(conversation.id),
                reference_digest(actor.id),
                result.failure_kind.value
                if result.failure_kind is not None
                else "unknown",
            )
        if not self._config.followup_enabled:
            return
        reminder = await self._record(
            conversation=conversation,
            actor=actor,
            joined_at=joined_at,
            delay_hours=self._config.followup_after_hours,
        )
        self.schedule(scheduler, reminder)

    async def start(self, *, scheduler: Scheduler) -> None:
        generation = self._generation = object()
        if not self._followup_enabled:
            return
        await self.schedule_pending(scheduler)
        if self._generation is not generation:
            return
        JobRegistry(scheduler, prefix=TEAM_AUDIT_JOB_PREFIX).add_wall_clock_interval(
            self.schedule_pending,
            minutes=FOLLOWUP_SCAN_INTERVAL_MINUTES,
            args=[scheduler],
            job_id="scan",
        )

    def stop(self, *, scheduler: Scheduler) -> None:
        self._generation = None
        JobRegistry(scheduler, prefix=TEAM_AUDIT_JOB_PREFIX).remove_by_prefix()

    async def schedule_pending(self, scheduler: Scheduler) -> None:
        if not self._followup_enabled:
            return
        generation = self._generation
        reminders = await self._store.list_all()
        if self._generation is not generation:
            return
        for reminder in reminders:
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
        key = (conversation, actor)
        if key in self._in_flight:
            return
        self._in_flight.add(key)
        generation = self._generation
        try:
            reminder = await self._pending_reminder(conversation, actor)
            if reminder is None:
                return

            if not await self._membership_probe.can_access(conversation):
                return
            present = await self._membership_probe.has_member(conversation, actor=actor)
            if self._generation is not generation:
                return
            if not present:
                await self._store.transition(reminder)
                return
            current = await self._pending_reminder(conversation, actor)
            if self._generation is not generation or current != reminder:
                return
            result = await self._messenger.send(
                conversation,
                OutboundMessage(
                    (MentionPart(actor), TextPart(self._followup_message(reminder)))
                ),
            )
            if not result.delivered:
                logger.warning(
                    "team audit followup send failed: conversation=%s:%s "
                    "actor=%s failure_kind=%s",
                    conversation.kind,
                    reference_digest(conversation.id),
                    reference_digest(actor.id),
                    result.failure_kind.value
                    if result.failure_kind is not None
                    else "unknown",
                )
            else:
                await self._finish_followup(scheduler, reminder)
        finally:
            self._in_flight.discard(key)

    async def _pending_reminder(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
    ) -> TeamAuditPendingReminder | None:
        if not self._followup_enabled:
            return None
        generation = self._generation
        reminder = await self._store.get(conversation, actor)
        if reminder is None or self._generation is not generation:
            return None
        final_disabled = (
            reminder.step >= FINAL_FOLLOWUP_STEP
            and not self._config.final_followup_enabled
        )
        if final_disabled or not self.active_for(conversation):
            await self._store.transition(reminder)
            return None
        if reminder.remind_at > datetime.now(timezone.utc):
            return None
        return reminder

    @property
    def _followup_enabled(self) -> bool:
        return (
            self._generation is not None
            and self._config.enabled
            and self._config.followup_enabled
        )

    async def _record(
        self,
        *,
        conversation: ConversationRef,
        actor: ActorRef,
        joined_at: datetime,
        delay_hours: float,
    ) -> TeamAuditPendingReminder:
        joined_at = _as_utc(joined_at)
        reminder = TeamAuditPendingReminder(
            conversation,
            actor,
            joined_at,
            joined_at + timedelta(hours=delay_hours),
            FIRST_FOLLOWUP_STEP,
        )
        await self._store.save(reminder)
        return reminder

    async def _finish_followup(
        self,
        scheduler: Scheduler,
        reminder: TeamAuditPendingReminder,
    ) -> None:
        if reminder.step < FINAL_FOLLOWUP_STEP and self._config.final_followup_enabled:
            final_reminder = reminder._replace(
                remind_at=reminder.joined_at
                + timedelta(hours=self._config.final_followup_after_hours),
                step=FINAL_FOLLOWUP_STEP,
            )
            if await self._store.transition(reminder, replacement=final_reminder):
                self.schedule(scheduler, final_reminder)
            return
        await self._store.transition(reminder)

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
            reminder.conversation.account_id or "",
            reminder.conversation.kind,
            reminder.conversation.id,
            reminder.actor.platform.value,
            reminder.actor.account_id or "",
            reminder.actor.kind,
            reminder.actor.id,
            reminder.actor.scope_id or "",
        )
    )
    return sha256(key.encode("utf-8")).hexdigest()[:24]
