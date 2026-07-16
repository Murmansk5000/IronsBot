import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message
from pytest import MonkeyPatch

from ironsbot.config.models.seer import (
    TeamResourceConfig,
    TeamResourceSubscriptionConfig,
)
from ironsbot.services.team_resource_adapter import TeamResourceResult
from ironsbot.shared.messaging.targets import MessageTarget, TargetSendSummary

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins import team_resource_subscription
from ironsbot.plugins.team_resource_subscription import runtime


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_register_team_resource_jobs_uses_standard_scheduler_fields(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        runtime,
        "get_team_resource_config",
        lambda: TeamResourceConfig(
            enabled=True,
            times=["22:30", "23:45"],
        ),
    )

    runtime._register_team_resource_jobs(scheduler)

    assert scheduler.jobs == [
        {
            "func": runtime._scan_team_resources,
            "trigger": "cron",
            "id": "team_resource_scan_2230",
            "replace_existing": True,
            "hour": 22,
            "minute": 30,
        },
        {
            "func": runtime._scan_team_resources,
            "trigger": "cron",
            "id": "team_resource_scan_2345",
            "replace_existing": True,
            "hour": 23,
            "minute": 45,
        },
    ]


def test_register_team_resource_jobs_skips_when_disabled(
    monkeypatch: MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    monkeypatch.setattr(
        runtime,
        "get_team_resource_config",
        lambda: TeamResourceConfig(enabled=False, times=["23:00"]),
    )

    runtime._register_team_resource_jobs(scheduler)

    assert scheduler.jobs == []


@pytest.mark.asyncio
async def test_team_resource_notice_leaves_bot_selection_to_router(
    monkeypatch: MonkeyPatch,
) -> None:
    subscription = TeamResourceSubscriptionConfig(
        group="group_a",
        team_ids=[1234567],
        threshold=1000,
    )
    sent: list[tuple[list[MessageTarget], Message, dict[str, object]]] = []

    async def fake_fetch(_team_id: int) -> TeamResourceResult:
        return TeamResourceResult(1234567, "示例战队", "", 500)

    async def fake_send_target_messages(
        targets: list[MessageTarget],
        message: Message,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent.append((targets, message, kwargs))
        return TargetSendSummary(targets, [])

    monkeypatch.setattr(
        team_resource_subscription,
        "_fetch_team_result_for_scan",
        fake_fetch,
    )
    monkeypatch.setattr(
        team_resource_subscription,
        "send_target_messages",
        fake_send_target_messages,
    )

    await team_resource_subscription._scan_subscription(
        987654321,
        subscription,
    )

    assert sent[0][0] == [MessageTarget("group", 987654321)]
    assert "bot" not in sent[0][2]
