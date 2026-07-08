from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, get_type_hints

from nonebot.adapters.onebot.v11 import Bot

from ironsbot.plugins import team_audit_welcome
from ironsbot.plugins.team_audit_welcome import runtime
from ironsbot.services.team_audit_welcome import TeamAuditPendingReminder

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest import MonkeyPatch


class FakeDriver:
    def __init__(self) -> None:
        self.bot_connect_handlers: list[Callable[[object], object]] = []

    def on_bot_connect(
        self,
        handler: Callable[[object], object],
    ) -> Callable[[object], object]:
        self.bot_connect_handlers.append(handler)
        return handler


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def _app_config(*, enabled: bool = True, followup_enabled: bool = True):
    return SimpleNamespace(
        message=SimpleNamespace(
            team_audit_welcome=SimpleNamespace(
                enabled=enabled,
                followup_enabled=followup_enabled,
            )
        )
    )


def test_team_audit_runtime_bot_connect_annotation_is_resolvable(
    monkeypatch: MonkeyPatch,
) -> None:
    registered_state = False
    monkeypatch.setitem(
        runtime._team_audit_welcome_runtime_state,
        "registered",
        registered_state,
    )
    driver = FakeDriver()
    scheduler = object()

    runtime._setup_team_audit_welcome_runtime(driver, scheduler)
    runtime._setup_team_audit_welcome_runtime(driver, scheduler)

    assert len(driver.bot_connect_handlers) == 1
    assert get_type_hints(driver.bot_connect_handlers[0])["bot"] is Bot


def test_schedule_team_audit_followup_uses_standard_scheduler_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    bot = SimpleNamespace(self_id=123456)
    remind_at = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    reminder = TeamAuditPendingReminder(
        group_id=987654321,
        user_id=1234567890,
        joined_at=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
        remind_at=remind_at,
    )
    monkeypatch.setattr(
        team_audit_welcome,
        "get_app_config",
        _app_config,
    )
    monkeypatch.setattr(
        team_audit_welcome,
        "_now_utc",
        lambda: datetime(2026, 7, 8, 11, 0, tzinfo=timezone.utc),
    )

    team_audit_welcome.schedule_team_audit_followup(
        scheduler,  # type: ignore[arg-type]
        bot,  # type: ignore[arg-type]
        reminder,
    )

    assert scheduler.jobs == [
        {
            "func": team_audit_welcome.send_team_audit_followup,
            "trigger": "date",
            "id": "team_audit_followup_987654321_1234567890",
            "replace_existing": True,
            "run_date": remind_at,
            "args": [bot, 987654321, 1234567890],
            "misfire_grace_time": 3600,
        }
    ]


def test_register_team_audit_followup_scan_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()
    bot = SimpleNamespace(self_id=123456)

    team_audit_welcome.register_team_audit_followup_scan(
        scheduler,  # type: ignore[arg-type]
        bot,  # type: ignore[arg-type]
    )

    assert scheduler.jobs == [
        {
            "func": team_audit_welcome.schedule_pending_team_audit_followups,
            "trigger": "interval",
            "id": "team_audit_followup_scan_123456",
            "replace_existing": True,
            "minutes": team_audit_welcome.FOLLOWUP_SCAN_INTERVAL_MINUTES,
            "args": [bot, scheduler],
        }
    ]
