from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.message import TeamAuditWelcomeConfig
from ironsbot.services.team_audit_welcome import TeamAuditPendingReminder
from ironsbot.shared.messaging.targets import MessageTarget, TargetSendSummary
from tests.helpers.runtime import build_test_runtime

os.environ["APP_CONFIG_PATH"] = str(
    Path(__file__).resolve().parents[1] / "config.example.toml"
)

from ironsbot.plugins.team_audit_welcome import followup

if TYPE_CHECKING:
    from pytest import MonkeyPatch

TEAM_AUDIT_RUNTIME = build_test_runtime(
    feature_config=FeatureConfig(
        group_policy={"987654321": ["team_audit"]},
        superuser_bypass=False,
    )
)


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


@dataclass(frozen=True)
class FakeBot:
    self_id: int = 123456


def _config(
    *,
    enabled: bool = True,
    followup_enabled: bool = True,
) -> TeamAuditWelcomeConfig:
    return TeamAuditWelcomeConfig(
        enabled=enabled,
        followup_enabled=followup_enabled,
        groups=[987654321],
    )


def test_schedule_team_audit_followup_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()
    config = _config()
    remind_at = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    reminder = TeamAuditPendingReminder(
        group_id=987654321,
        user_id=1234567890,
        joined_at=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
        remind_at=remind_at,
    )
    followup.schedule_team_audit_followup(
        scheduler,  # type: ignore[arg-type]
        reminder,
        config=config,
        features=TEAM_AUDIT_RUNTIME.features,
        delivery=TEAM_AUDIT_RUNTIME.delivery,
        now=datetime(2026, 7, 8, 11, 0, tzinfo=timezone.utc),
    )

    assert scheduler.jobs == [
        {
            "func": followup.send_team_audit_followup,
            "trigger": "date",
            "id": "team_audit_followup_987654321_1234567890",
            "replace_existing": True,
            "run_date": remind_at,
            "args": [987654321, 1234567890],
            "kwargs": {
                "config": config,
                "scheduler": scheduler,
                "features": TEAM_AUDIT_RUNTIME.features,
                "delivery": TEAM_AUDIT_RUNTIME.delivery,
            },
            "misfire_grace_time": 3600,
        }
    ]


def test_register_team_audit_followup_scan_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()
    config = _config()
    followup.register_team_audit_followup_scan(
        scheduler,  # type: ignore[arg-type]
        config=config,
        features=TEAM_AUDIT_RUNTIME.features,
        delivery=TEAM_AUDIT_RUNTIME.delivery,
    )

    assert scheduler.jobs == [
        {
            "func": followup.schedule_pending_team_audit_followups,
            "trigger": "interval",
            "id": "team_audit_followup_scan",
            "replace_existing": True,
            "minutes": followup.FOLLOWUP_SCAN_INTERVAL_MINUTES,
            "args": [scheduler],
            "kwargs": {
                "config": config,
                "features": TEAM_AUDIT_RUNTIME.features,
                "delivery": TEAM_AUDIT_RUNTIME.delivery,
            },
        }
    ]


def test_team_audit_followup_uses_group_routed_bot(
    monkeypatch: MonkeyPatch,
) -> None:
    bot = FakeBot()
    config = _config()
    scheduler = FakeScheduler()
    reminder = TeamAuditPendingReminder(
        group_id=987654321,
        user_id=1234567890,
        joined_at=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
        remind_at=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
    )
    sent: dict[str, object] = {}

    async def fake_send_target_messages(
        _delivery: object,
        targets: list[MessageTarget],
        _message: object,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent.update(targets=targets, **kwargs)
        return TargetSendSummary(targets, [])

    monkeypatch.setattr(
        followup,
        "get_team_audit_pending_reminder",
        lambda _path, **_kwargs: reminder,
    )
    monkeypatch.setattr(followup, "get_bot_for_group", lambda _group_id: bot)
    monkeypatch.setattr(followup, "_bot_can_access_group", _async_true)
    monkeypatch.setattr(followup, "_is_member_still_in_group", _async_true)
    monkeypatch.setattr(followup, "send_target_messages", fake_send_target_messages)
    monkeypatch.setattr(
        followup,
        "_finish_sent_followup",
        lambda _reminder, **_kwargs: None,
    )

    asyncio.run(
        followup.send_team_audit_followup(
            987654321,
            1234567890,
            config=config,
            scheduler=scheduler,  # type: ignore[arg-type]
            features=TEAM_AUDIT_RUNTIME.features,
            delivery=TEAM_AUDIT_RUNTIME.delivery,
        )
    )

    assert sent["targets"] == [MessageTarget("group", 987654321)]
    assert sent["bot"] is bot


def test_team_audit_followup_keeps_pending_when_bot_cannot_access_group(
    monkeypatch: MonkeyPatch,
) -> None:
    bot = FakeBot()
    config = _config()
    scheduler = FakeScheduler()
    reminder = TeamAuditPendingReminder(
        group_id=987654321,
        user_id=1234567890,
        joined_at=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
        remind_at=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
    )
    cleared = False

    async def inaccessible(*_args: object, **_kwargs: object) -> bool:
        return False

    def clear_pending(_path: object, **_kwargs: object) -> None:
        nonlocal cleared
        cleared = True

    monkeypatch.setattr(
        followup,
        "get_team_audit_pending_reminder",
        lambda _path, **_kwargs: reminder,
    )
    monkeypatch.setattr(followup, "get_bot_for_group", lambda _group_id: bot)
    monkeypatch.setattr(followup, "_bot_can_access_group", inaccessible)
    monkeypatch.setattr(
        followup,
        "clear_team_audit_pending_reminder",
        clear_pending,
    )

    asyncio.run(
        followup.send_team_audit_followup(
            987654321,
            1234567890,
            config=config,
            scheduler=scheduler,  # type: ignore[arg-type]
            features=TEAM_AUDIT_RUNTIME.features,
            delivery=TEAM_AUDIT_RUNTIME.delivery,
        )
    )

    assert not cleared


async def _async_true(*_args: object, **_kwargs: object) -> bool:
    return True
