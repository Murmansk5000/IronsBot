import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message
from pytest import MonkeyPatch

from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.services.team_resource_adapter import TeamResourceResult
from ironsbot.services.team_resource_subscriptions import TeamResourceSubscription
from ironsbot.shared.messaging.targets import MessageTarget, TargetSendSummary

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins import team_resource_subscription
from ironsbot.plugins.team_resource_subscription import runtime

TEAM_ID = 1234567
TEAM_THRESHOLD = 2000


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


def test_parse_team_resource_manage_commands() -> None:
    add = team_resource_subscription._parse_team_resource_manage_command(
        f"订阅战队{TEAM_ID} {TEAM_THRESHOLD}"
    )
    remove = team_resource_subscription._parse_team_resource_manage_command(
        f"取消订阅战队{TEAM_ID}"
    )
    list_command = team_resource_subscription._parse_team_resource_manage_command(
        "战队订阅"
    )

    assert add is not None
    assert add.action == "add"
    assert add.team_id == TEAM_ID
    assert add.threshold == TEAM_THRESHOLD
    assert remove is not None
    assert remove.action == "remove"
    assert remove.team_id == TEAM_ID
    assert list_command is not None
    assert list_command.action == "list"


@pytest.mark.parametrize("text", ["是", "yes", "YES", " y ", "确认", "确定"])
def test_parse_team_resource_prompt_choice_accepts_yes(text: str) -> None:
    assert team_resource_subscription.parse_team_resource_prompt_choice(text) is True


@pytest.mark.parametrize("text", ["否", "no", "NO", " n ", "取消"])
def test_parse_team_resource_prompt_choice_accepts_no(text: str) -> None:
    assert team_resource_subscription.parse_team_resource_prompt_choice(text) is False


@pytest.mark.parametrize("text", ["", "订阅", "yes please", "不订阅"])
def test_parse_team_resource_prompt_choice_ignores_other_text(text: str) -> None:
    assert team_resource_subscription.parse_team_resource_prompt_choice(text) is None


@pytest.mark.asyncio
async def test_team_resource_notice_leaves_bot_selection_to_router(
    monkeypatch: MonkeyPatch,
) -> None:
    subscription = TeamResourceSubscription(
        group_id=987654321,
        team_id=TEAM_ID,
        team_name="示例战队",
        threshold=1000,
        at_user_ids=(),
        created_by=1,
        updated_by=1,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    sent: list[tuple[list[MessageTarget], Message, dict[str, object]]] = []

    async def fake_fetch(_team_id: int) -> TeamResourceResult:
        return TeamResourceResult(TEAM_ID, "示例战队", "", 500)

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
        subscription,
    )

    assert sent[0][0] == [MessageTarget("group", 987654321)]
    assert "bot" not in sent[0][2]
