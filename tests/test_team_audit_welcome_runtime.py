from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

from ironsbot.config.models.messaging import TeamAuditWelcomeConfig
from ironsbot.core.features import FeatureConfig
from ironsbot.core.messaging import MessageTarget, TargetSendSummary
from ironsbot.services.team.audit import (
    FINAL_FOLLOWUP_STEP,
    FOLLOWUP_SCAN_INTERVAL_MINUTES,
    TeamAuditPendingReminder,
    TeamAuditService,
)
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.services.messaging.delivery import MessageDelivery

GROUP_ID = 987654321
USER_ID = 1234567890
JOINED_AT = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
REMIND_AT = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)

TEAM_AUDIT_RUNTIME = build_test_runtime(
    feature_config=FeatureConfig(
        group_policy={str(GROUP_ID): ["team_audit"]},
        superuser_bypass=False,
    )
)


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


@dataclass(frozen=True)
class FakeBot:
    self_id: int = 123456


@dataclass
class FakeStore:
    reminder: TeamAuditPendingReminder | None = None
    cleared: bool = False

    def save(self, reminder: TeamAuditPendingReminder) -> None:
        self.reminder = reminder

    def get(self, group_id: int, user_id: int) -> TeamAuditPendingReminder | None:
        assert (group_id, user_id) == (GROUP_ID, USER_ID)
        return self.reminder

    def list_all(self) -> list[TeamAuditPendingReminder]:
        return [self.reminder] if self.reminder is not None else []

    def clear(self, group_id: int, user_id: int) -> None:
        assert (group_id, user_id) == (GROUP_ID, USER_ID)
        self.cleared = True
        self.reminder = None


@dataclass
class FakeDelivery:
    bot: FakeBot
    sent: list[dict[str, Any]]

    def bot_for_target(self, _target: MessageTarget) -> FakeBot:
        return self.bot

    async def send_targets(
        self,
        targets: Iterable[MessageTarget],
        message: Any,
        **kwargs: Any,
    ) -> TargetSendSummary:
        target_list = list(targets)
        self.sent.append(
            {"targets": target_list, "message": message, **kwargs}
        )
        return TargetSendSummary(target_list, [])


@dataclass
class FakeGroupProbe:
    accessible: bool = True
    member_present: bool = True

    async def can_access(self, bot: Any, *, group_id: int) -> bool:
        del bot
        assert group_id == GROUP_ID
        return self.accessible

    async def has_member(
        self,
        bot: Any,
        *,
        group_id: int,
        user_id: int,
    ) -> bool:
        del bot
        assert (group_id, user_id) == (GROUP_ID, USER_ID)
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
    return TeamAuditPendingReminder(
        GROUP_ID,
        USER_ID,
        JOINED_AT,
        REMIND_AT,
    )


def _service(
    config: TeamAuditWelcomeConfig,
    reminder: TeamAuditPendingReminder | None = None,
    *,
    accessible: bool = True,
    member_present: bool = True,
) -> tuple[TeamAuditService, FakeStore, FakeDelivery, FakeGroupProbe]:
    store = FakeStore(reminder)
    delivery = FakeDelivery(FakeBot(), [])
    probe = FakeGroupProbe(accessible, member_present)
    service = TeamAuditService(
        config,
        store,
        TEAM_AUDIT_RUNTIME.features,
        cast("MessageDelivery", delivery),
        probe,
    )
    return service, store, delivery, probe


def test_schedule_team_audit_followup_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()
    service, _, _, _ = _service(_config())
    reminder = _reminder()

    service.schedule(
        scheduler,
        reminder,
        now=datetime(2026, 7, 8, 11, 0, tzinfo=timezone.utc),
    )

    assert scheduler.jobs == [
        {
            "func": service.send_followup,
            "trigger": "date",
            "id": f"team_audit_followup_{GROUP_ID}_{USER_ID}",
            "replace_existing": True,
            "run_date": REMIND_AT,
            "args": [GROUP_ID, USER_ID],
            "kwargs": {"scheduler": scheduler},
            "misfire_grace_time": 3600,
        }
    ]


def test_start_team_audit_followups_registers_scan() -> None:
    scheduler = FakeScheduler()
    service, _, _, _ = _service(_config())

    asyncio.run(service.start(FakeBot(), scheduler=scheduler))

    assert scheduler.jobs == [
        {
            "func": service.schedule_pending,
            "trigger": "cron",
            "id": "team_audit_followup_scan",
            "replace_existing": True,
            "minute": f"*/{FOLLOWUP_SCAN_INTERVAL_MINUTES}",
            "second": 0,
            "args": [scheduler],
        }
    ]


def test_team_audit_welcome_sends_and_schedules_followup() -> None:
    scheduler = FakeScheduler()
    service, store, delivery, _ = _service(_config())

    asyncio.run(
        service.welcome(
            group_id=GROUP_ID,
            user_id=USER_ID,
            joined_at=JOINED_AT,
            scheduler=scheduler,
            bot=delivery.bot,
        )
    )

    assert delivery.sent[0]["targets"] == [
        MessageTarget("group", GROUP_ID, (USER_ID,))
    ]
    assert delivery.sent[0]["bot"] is delivery.bot
    assert store.reminder is not None
    assert scheduler.jobs[0]["func"] == service.send_followup


def test_team_audit_followup_uses_group_routed_bot() -> None:
    scheduler = FakeScheduler()
    service, store, delivery, _ = _service(_config(), _reminder())

    asyncio.run(
        service.send_followup(GROUP_ID, USER_ID, scheduler=scheduler)
    )

    assert delivery.sent[0]["targets"] == [
        MessageTarget("group", GROUP_ID, (USER_ID,))
    ]
    assert delivery.sent[0]["bot"] is delivery.bot
    assert store.reminder is not None
    assert store.reminder.step == FINAL_FOLLOWUP_STEP


def test_team_audit_followup_keeps_pending_when_bot_cannot_access_group() -> None:
    scheduler = FakeScheduler()
    reminder = _reminder()
    service, store, delivery, _ = _service(
        _config(),
        reminder,
        accessible=False,
    )

    asyncio.run(
        service.send_followup(GROUP_ID, USER_ID, scheduler=scheduler)
    )

    assert store.reminder == reminder
    assert not store.cleared
    assert delivery.sent == []


def test_team_audit_followup_clears_departed_member() -> None:
    scheduler = FakeScheduler()
    service, store, delivery, _ = _service(
        _config(),
        _reminder(),
        member_present=False,
    )

    asyncio.run(
        service.send_followup(GROUP_ID, USER_ID, scheduler=scheduler)
    )

    assert store.cleared
    assert delivery.sent == []
