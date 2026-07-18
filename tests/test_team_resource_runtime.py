import os
from pathlib import Path
from typing import cast

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.matcher import Matcher
from pytest import MonkeyPatch

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.runtime import HeadlessConfig, HeadlessNoticeConfig
from ironsbot.config.models.secrets import CredentialsConfig
from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.team_resource_adapter import TeamResourceResult
from ironsbot.services.team_resource_subscriptions import (
    TeamResourceService,
    TeamResourceSubscription,
)
from ironsbot.shared.messaging.targets import MessageTarget, TargetSendSummary
from tests.helpers.onebot_events import group_message_event
from tests.helpers.runtime import build_test_runtime

os.environ["APP_CONFIG_PATH"] = str(
    Path(__file__).resolve().parents[1] / "config.example.toml"
)

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins import team_resource_subscription
from ironsbot.plugins.team_resource_subscription import runtime

TEAM_ID = 1234567
TEAM_THRESHOLD = 2000
TEST_RUNTIME = build_test_runtime(
    feature_config=FeatureConfig(
        group_policy={"456": ["team_resource_subscription"]},
    )
)
HEADLESS = HeadlessService(
    ClientManager(),
    CredentialsConfig(),
    HeadlessConfig(),
    HeadlessNoticeConfig(),
    TEST_RUNTIME.admin_notices,
)
TEAM_RESOURCE_REGISTRY = TEST_RUNTIME.matcher_registry()
TEAM_RESOURCE_SERVICE = TeamResourceService.build(
    TeamResourceConfig(),
    {},
    TEST_RUNTIME.features,
    TEST_RUNTIME.delivery,
)
team_resource_subscription.install(
    TEAM_RESOURCE_REGISTRY,
    HEADLESS,
    TEAM_RESOURCE_SERVICE,
)


def _team_resource_matcher(command_id: str) -> type[Matcher]:
    for matcher in TEAM_RESOURCE_REGISTRY.message_matchers:
        if TEAM_RESOURCE_REGISTRY.cooldown.registration(matcher) == (
            "command",
            command_id,
        ):
            return matcher
    raise AssertionError(command_id)


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})


def test_register_team_resource_jobs_uses_standard_scheduler_fields(
) -> None:
    scheduler = FakeScheduler()
    service = TeamResourceService.build(
        TeamResourceConfig(
            enabled=True,
            times=["22:30", "23:45"],
        ),
        {},
        TEST_RUNTIME.features,
        TEST_RUNTIME.delivery,
    )

    runtime.register_team_resource_jobs(scheduler, HEADLESS, service)

    scan = scheduler.jobs[0]["func"]
    assert scheduler.jobs == [
        {
            "func": scan,
            "trigger": "cron",
            "id": "team_resource_scan_2230",
            "replace_existing": True,
            "hour": 22,
            "minute": 30,
        },
        {
            "func": scan,
            "trigger": "cron",
            "id": "team_resource_scan_2345",
            "replace_existing": True,
            "hour": 23,
            "minute": 45,
        },
    ]


def test_register_team_resource_jobs_skips_when_disabled(
) -> None:
    scheduler = FakeScheduler()
    service = TeamResourceService.build(
        TeamResourceConfig(enabled=False, times=["23:00"]),
        {},
        TEST_RUNTIME.features,
        TEST_RUNTIME.delivery,
    )

    runtime.register_team_resource_jobs(scheduler, HEADLESS, service)

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


def test_parse_team_resource_manage_command_ignores_manual_at_id_as_threshold(
) -> None:
    command = team_resource_subscription._parse_team_resource_manage_command(
        f"订阅战队{TEAM_ID} @2315721708"
    )

    assert command is not None
    assert command.team_id == TEAM_ID
    assert command.threshold is None
    assert team_resource_subscription._has_manual_qq_mention(
        f"订阅战队{TEAM_ID} @2315721708"
    )


def test_team_resource_manage_uses_command_cooldown() -> None:
    assert TEAM_RESOURCE_REGISTRY.cooldown.registration(
        _team_resource_matcher("team_resource_manage"),
    ) == (
        "command",
        "team_resource_manage",
    )


@pytest.mark.asyncio
async def test_team_resource_manage_rule_allows_qq_mentions_but_not_replies(
) -> None:
    message = Message(
        [
            MessageSegment.text(f"订阅战队{TEAM_ID} {TEAM_THRESHOLD} "),
            MessageSegment.at(234),
        ]
    )
    event = group_message_event(message=message, sender={"role": "admin"})
    replied_event = group_message_event(
        message=message,
        sender={"role": "admin"},
        reply_sender_user_id=345,
    )

    assert team_resource_subscription._at_user_ids_from_event(event) == (234,)
    matcher = _team_resource_matcher("team_resource_manage")
    assert await matcher.rule(
        cast("Bot", None),
        event,
        {},
    )
    assert not await matcher.rule(
        cast("Bot", None),
        replied_event,
        {},
    )


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

    async def fake_fetch(
        _team_id: int,
        _headless: HeadlessService,
        _service: TeamResourceService,
        *,
        mode: str,
    ) -> TeamResourceResult:
        assert mode == "scan"
        return TeamResourceResult(TEAM_ID, "示例战队", "", 500)

    async def fake_send_target_messages(
        _delivery: object,
        targets: list[MessageTarget],
        message: Message,
        **kwargs: object,
    ) -> TargetSendSummary:
        sent.append((targets, message, kwargs))
        return TargetSendSummary(targets, [])

    monkeypatch.setattr(
        team_resource_subscription,
        "_query_team_resource",
        fake_fetch,
    )
    monkeypatch.setattr(
        team_resource_subscription,
        "send_target_messages",
        fake_send_target_messages,
    )

    await team_resource_subscription._scan_subscription(
        subscription,
        HEADLESS,
        TEAM_RESOURCE_SERVICE,
    )

    assert sent[0][0] == [MessageTarget("group", 987654321)]
    assert "bot" not in sent[0][2]
