from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ironsbot.config.models.messaging import TeamAuditWelcomeConfig
from ironsbot.core.outbound import (
    DeliveryCapabilities,
    OutboundMessage,
    SendResult,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.team.audit import (
    FINAL_FOLLOWUP_STEP,
    FOLLOWUP_SCAN_INTERVAL_MINUTES,
    TeamAuditPendingReminder,
    TeamAuditService,
)

GROUP_ID = "987654321"
USER_ID = "1234567890"
CONVERSATION = ConversationRef(Platform.ONEBOT, "group", GROUP_ID)
ACTOR = ActorRef(
    Platform.ONEBOT,
    USER_ID,
    kind="member",
    scope_id=GROUP_ID,
)
JOINED_AT = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
REMIND_AT = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)


class FakeJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    def add_job(self, func: Any, trigger: str, **kwargs: Any) -> FakeJob:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})
        return FakeJob(str(kwargs["id"]))

    def get_jobs(self) -> list[FakeJob]:
        return [FakeJob(str(job["id"])) for job in self.jobs]

    def remove_job(self, job_id: str) -> None:
        self.jobs = [job for job in self.jobs if job["id"] != job_id]


@dataclass
class FakeStore:
    reminder: TeamAuditPendingReminder | None = None
    cleared: bool = False

    def save(self, reminder: TeamAuditPendingReminder) -> None:
        self.reminder = reminder

    def get(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
    ) -> TeamAuditPendingReminder | None:
        assert (conversation, actor) == (CONVERSATION, ACTOR)
        return self.reminder

    def list_all(self) -> list[TeamAuditPendingReminder]:
        return [self.reminder] if self.reminder is not None else []

    def clear(self, conversation: ConversationRef, actor: ActorRef) -> None:
        assert (conversation, actor) == (CONVERSATION, ACTOR)
        self.cleared = True
        self.reminder = None


@dataclass
class FakePolicy:
    active: bool = True

    def enabled_for(self, conversation: ConversationRef) -> bool:
        assert conversation == CONVERSATION
        return self.active


@dataclass
class FakeMessenger:
    delivered: bool = True
    sent: list[tuple[ConversationRef, OutboundMessage]] | None = None

    def __post_init__(self) -> None:
        if self.sent is None:
            self.sent = []

    def capabilities_for(self, _conversation: ConversationRef) -> DeliveryCapabilities:
        return DeliveryCapabilities(
            can_reply_to_event=True,
            can_send_proactively=True,
            can_mention_members=True,
            supports_group_context=True,
            supports_private_context=True,
            supports_images=True,
        )

    async def send(
        self,
        conversation: ConversationRef,
        message: OutboundMessage,
    ) -> SendResult:
        assert self.sent is not None
        self.sent.append((conversation, message))
        if self.delivered:
            return SendResult(delivered=True, message_id="1")
        return SendResult(delivered=False, error_code="delivery_failed")

    async def reply(self, *_args: object, **_kwargs: object) -> SendResult:
        raise AssertionError


@dataclass
class FakeMembershipProbe:
    accessible: bool = True
    member_present: bool = True

    async def can_access(self, conversation: ConversationRef) -> bool:
        assert conversation == CONVERSATION
        return self.accessible

    async def has_member(
        self,
        conversation: ConversationRef,
        *,
        actor: ActorRef,
    ) -> bool:
        assert (conversation, actor) == (CONVERSATION, ACTOR)
        return self.member_present


def _config(
    *,
    enabled: bool = True,
    followup_enabled: bool = True,
) -> TeamAuditWelcomeConfig:
    return TeamAuditWelcomeConfig(
        enabled=enabled,
        followup_enabled=followup_enabled,
    )


def _reminder() -> TeamAuditPendingReminder:
    return TeamAuditPendingReminder(CONVERSATION, ACTOR, JOINED_AT, REMIND_AT)


@dataclass(frozen=True)
class _ServiceConditions:
    active: bool = True
    delivered: bool = True
    accessible: bool = True
    member_present: bool = True


def _service(
    config: TeamAuditWelcomeConfig,
    reminder: TeamAuditPendingReminder | None = None,
    *,
    conditions: _ServiceConditions = _ServiceConditions(),
) -> tuple[TeamAuditService, FakeStore, FakeMessenger, FakeMembershipProbe]:
    store = FakeStore(reminder)
    messenger = FakeMessenger(delivered=conditions.delivered)
    probe = FakeMembershipProbe(
        accessible=conditions.accessible,
        member_present=conditions.member_present,
    )
    service = TeamAuditService(
        config,
        store,
        FakePolicy(conditions.active),
        messenger,
        probe,
    )
    return service, store, messenger, probe


def test_schedule_team_audit_followup_uses_platform_safe_job_key() -> None:
    scheduler = FakeScheduler()
    service, _, _, _ = _service(_config())
    reminder = _reminder()

    service.schedule(
        scheduler,
        reminder,
        now=datetime(2026, 7, 8, 11, 0, tzinfo=timezone.utc),
    )

    assert scheduler.jobs[0]["func"] == service.send_followup
    assert scheduler.jobs[0]["trigger"] == "date"
    assert scheduler.jobs[0]["id"].startswith("team_audit_followup_")
    assert scheduler.jobs[0]["run_date"] == REMIND_AT
    assert scheduler.jobs[0]["args"] == [CONVERSATION, ACTOR]
    assert scheduler.jobs[0]["kwargs"] == {"scheduler": scheduler}


def test_start_team_audit_followups_registers_scan() -> None:
    scheduler = FakeScheduler()
    service, _, _, _ = _service(_config())

    asyncio.run(service.start(scheduler=scheduler))

    assert scheduler.jobs == [
        {
            "func": service.schedule_pending,
            "trigger": "interval",
            "id": "team_audit_followup_scan",
            "replace_existing": True,
            "minutes": FOLLOWUP_SCAN_INTERVAL_MINUTES,
            "args": [scheduler],
        }
    ]


def test_team_audit_welcome_sends_mention_and_schedules_followup() -> None:
    scheduler = FakeScheduler()
    service, store, messenger, _ = _service(_config())

    asyncio.run(
        service.welcome(
            conversation=CONVERSATION,
            actor=ACTOR,
            joined_at=JOINED_AT,
            scheduler=scheduler,
        )
    )

    assert messenger.sent is not None
    assert messenger.sent[0][0] == CONVERSATION
    assert messenger.sent[0][1].parts[0].actor == ACTOR
    assert store.reminder is not None
    assert scheduler.jobs[0]["func"] == service.send_followup


def test_team_audit_followup_uses_platform_messenger() -> None:
    scheduler = FakeScheduler()
    service, store, messenger, _ = _service(_config(), _reminder())

    asyncio.run(service.send_followup(CONVERSATION, ACTOR, scheduler=scheduler))

    assert messenger.sent is not None
    assert messenger.sent[0][0] == CONVERSATION
    assert messenger.sent[0][1].parts[0].actor == ACTOR
    assert store.reminder is not None
    assert store.reminder.step == FINAL_FOLLOWUP_STEP


def test_team_audit_followup_keeps_pending_when_group_is_inaccessible() -> None:
    scheduler = FakeScheduler()
    reminder = _reminder()
    service, store, messenger, _ = _service(
        _config(),
        reminder,
        conditions=_ServiceConditions(accessible=False),
    )

    asyncio.run(service.send_followup(CONVERSATION, ACTOR, scheduler=scheduler))

    assert store.reminder == reminder
    assert not store.cleared
    assert messenger.sent == []


def test_team_audit_followup_clears_departed_member() -> None:
    scheduler = FakeScheduler()
    service, store, messenger, _ = _service(
        _config(),
        _reminder(),
        conditions=_ServiceConditions(member_present=False),
    )

    asyncio.run(service.send_followup(CONVERSATION, ACTOR, scheduler=scheduler))

    assert store.cleared
    assert messenger.sent == []
