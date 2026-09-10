from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, MagicMock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from pytest import MonkeyPatch

from ironsbot.config.models.operations import HeadlessConfig, HeadlessNoticeConfig
from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.core.features import FeatureConfig
from ironsbot.core.messaging import MessageTarget, TargetSendSummary
from ironsbot.core.onebot_references import OneBotReferenceResolver
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.integrations.onebot.delivery import OneBotDelivery
from ironsbot.integrations.storage.team_resources import (
    TeamResourceSubscriptionStore,
)
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.seer.team import PlayerTeamLookup
from ironsbot.services.team.resource import (
    TeamOverviewItem,
    TeamResourceResult,
    TeamResourceService,
    TeamResourceSubscriptionTarget,
    TeamResourceSubscriptionUpdate,
)
from tests.helpers.onebot_events import group_message_event, private_message_event
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot
    from nonebot.matcher import Matcher

os.environ["APP_CONFIG_PATH"] = str(
    Path(__file__).resolve().parents[1] / "config.example.toml"
)

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.team import resource

TEAM_ID = 1234567
TEAM_THRESHOLD = 2000
GROUP_ID = 456
TEST_RUNTIME = build_test_runtime(
    feature_config=FeatureConfig(
        group_policy={"456": ["team_resource_subscription"]},
    )
)
HEADLESS = HeadlessService(
    ClientManager(TEST_RUNTIME.tasks.create),
    HeadlessConfig(),
    HeadlessNoticeConfig(),
    TEST_RUNTIME.admin_notices,
)


def _service(
    config: TeamResourceConfig,
    state_path: Path = Path("data/state/qq_state.sqlite"),
) -> TeamResourceService:
    return TeamResourceService(
        config,
        TeamResourceSubscriptionStore(state_path),
        HEADLESS,
        OneBotReferenceResolver({}, {}),
        TEST_RUNTIME.features,
        TEST_RUNTIME.delivery,
    )


TEAM_RESOURCE_REGISTRY = TEST_RUNTIME.matcher_registry()
TEAM_RESOURCE_SERVICE = _service(TeamResourceConfig())
resource.install(
    TEAM_RESOURCE_REGISTRY,
    TEAM_RESOURCE_SERVICE,
    MagicMock(),
    MagicMock(),
)


def _team_resource_matcher(command_id: str) -> type[Matcher]:
    for matcher in TEAM_RESOURCE_REGISTRY.message_matchers:
        if TEAM_RESOURCE_REGISTRY.cooldown_registration(matcher) == (
            "command",
            command_id,
        ):
            return matcher
    raise AssertionError(command_id)


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(
        self,
        func: Any,
        trigger: str,
        **kwargs: Any,
    ) -> FakeJob:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})
        return FakeJob(str(kwargs["id"]))

    def get_jobs(self) -> list[FakeJob]:
        return [FakeJob(str(job["id"])) for job in self.jobs]

    def remove_job(self, job_id: str) -> None:
        self.jobs = [job for job in self.jobs if job["id"] != job_id]


class FakeJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id


def test_register_team_resource_jobs_uses_standard_scheduler_fields() -> None:
    scheduler = FakeScheduler()
    service = _service(
        TeamResourceConfig(
            enabled=True,
            times=["22:30", "23:45"],
        )
    )

    service.register_jobs(scheduler)

    scan = scheduler.jobs[0]["func"]
    assert scheduler.jobs == [
        {
            "func": scan,
            "trigger": "cron",
            "id": "team_resource_scan_223000",
            "replace_existing": True,
            "hour": 22,
            "minute": 30,
            "second": 0,
        },
        {
            "func": scan,
            "trigger": "cron",
            "id": "team_resource_scan_234500",
            "replace_existing": True,
            "hour": 23,
            "minute": 45,
            "second": 0,
        },
    ]


def test_register_team_resource_jobs_skips_when_disabled() -> None:
    scheduler = FakeScheduler()
    service = _service(TeamResourceConfig(enabled=False, times=["23:00"]))

    service.register_jobs(scheduler)

    assert scheduler.jobs == []


def test_parse_team_resource_manage_commands() -> None:
    add = TEAM_RESOURCE_SERVICE.parse_manage(f"订阅战队{TEAM_ID} {TEAM_THRESHOLD}")
    remove = TEAM_RESOURCE_SERVICE.parse_manage(f"取消订阅战队{TEAM_ID}")
    list_command = TEAM_RESOURCE_SERVICE.parse_manage("战队订阅")

    assert add is not None
    assert add.action == "add"
    assert add.team_id == TEAM_ID
    assert add.threshold == TEAM_THRESHOLD
    assert remove is not None
    assert remove.action == "remove"
    assert remove.team_id == TEAM_ID
    assert list_command is not None
    assert list_command.action == "list"


def test_parse_team_resource_manage_command_ignores_manual_at_id_as_threshold() -> None:
    command = TEAM_RESOURCE_SERVICE.parse_manage(f"订阅战队{TEAM_ID} @2315721708")

    assert command is not None
    assert command.team_id == TEAM_ID
    assert command.threshold is None
    assert command.has_manual_mention


def test_team_resource_manage_uses_command_cooldown() -> None:
    assert TEAM_RESOURCE_REGISTRY.cooldown_registration(
        _team_resource_matcher("team_resource_manage"),
    ) == (
        "command",
        "team_resource_manage",
    )


def test_team_resource_manage_rule_claims_member_mutation_for_permission_reply(
) -> None:
    event = group_message_event(
        f"订阅战队{TEAM_ID} {TEAM_THRESHOLD}",
        group_id=GROUP_ID,
        sender={"role": "member"},
    )

    target = resource._subscription_target(event)
    assert target is not None
    assert TEAM_RESOURCE_SERVICE.allows_target(event.user_id, target)
    assert resource._is_team_resource_manage(
        event,
        service=TEAM_RESOURCE_SERVICE,
    )


@pytest.mark.asyncio
async def test_team_resource_manage_tells_member_that_admin_permission_is_required(
    monkeypatch: MonkeyPatch,
) -> None:
    event = group_message_event(
        f"订阅战队{TEAM_ID} {TEAM_THRESHOLD}",
        group_id=GROUP_ID,
        sender={"role": "member"},
    )
    finish = AsyncMock()
    matcher = cast("Matcher", object())
    monkeypatch.setattr(resource, "finish_event_reply", finish)

    await resource.handle_team_resource_manage(
        matcher,
        event,
        TEAM_RESOURCE_SERVICE,
        cast("Any", object()),
    )

    finish.assert_awaited_once_with(
        matcher,
        event,
        "只有群主、管理员或超级管理员可以修改战队订阅。",
    )


def test_team_resource_manage_rule_ignores_disabled_conversation() -> None:
    event = group_message_event(
        f"订阅战队{TEAM_ID} {TEAM_THRESHOLD}",
        group_id=999,
        sender={"role": "admin"},
    )

    assert not resource._is_team_resource_manage(
        event,
        service=TEAM_RESOURCE_SERVICE,
    )


def test_team_resource_group_target_defaults_to_operator_without_mentions() -> None:
    target = TeamResourceSubscriptionTarget("group", GROUP_ID)

    assert resource._with_default_group_reminder(target, 123) == (
        "group",
        GROUP_ID,
        (123,),
    )
    mentioned = TeamResourceSubscriptionTarget("group", GROUP_ID, (234,))
    assert resource._with_default_group_reminder(mentioned, 123) == mentioned


@pytest.mark.asyncio
async def test_group_overview_prepends_the_requesters_bound_team() -> None:
    event = group_message_event("战队", user_id=123)
    service = MagicMock()
    service.query_overview = AsyncMock(
        return_value=(TeamOverviewItem(9876543, "所属战队", 60, 500),)
    )
    player = MagicMock()
    player.default_player_id.return_value = 148758762
    team_query = MagicMock()
    team_query.lookup_player_team = AsyncMock(
        return_value=PlayerTeamLookup(team_id=9876543)
    )
    menus = MagicMock(player=player, query=team_query)
    menus.open = AsyncMock()

    await resource.handle_team_resource(
        cast("Matcher", object()),
        event,
        service,
        menus,
    )

    service.query_overview.assert_awaited_once_with(
        TeamResourceSubscriptionTarget("group", GROUP_ID),
        first_team_id=9876543,
    )
    menus.open.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_overview_includes_the_requesters_bound_team() -> None:
    event = private_message_event("战队", user_id=123)
    service = MagicMock()
    service.is_superuser.return_value = False
    service.query_overview = AsyncMock(
        return_value=(TeamOverviewItem(9876543, "所属战队", 60, 500),)
    )
    player = MagicMock()
    player.default_player_id.return_value = 148758762
    team_query = MagicMock()
    team_query.lookup_player_team = AsyncMock(
        return_value=PlayerTeamLookup(team_id=9876543)
    )
    menus = MagicMock(player=player, query=team_query)
    menus.open = AsyncMock()

    await resource.handle_team_resource(
        cast("Matcher", object()),
        event,
        service,
        menus,
    )

    service.query_overview.assert_awaited_once_with(
        TeamResourceSubscriptionTarget("private", 123),
        first_team_id=9876543,
    )
    menus.open.assert_awaited_once()


@pytest.mark.asyncio
async def test_group_overview_keeps_subscriptions_when_bound_team_lookup_fails(
) -> None:
    event = group_message_event("战队", user_id=123)
    service = MagicMock()
    service.query_overview = AsyncMock(
        return_value=(TeamOverviewItem(1234567, "订阅战队", 60, 500),)
    )
    player = MagicMock()
    player.default_player_id.return_value = 148758762
    team_query = MagicMock()
    team_query.lookup_player_team = AsyncMock(
        return_value=PlayerTeamLookup(error="连接已断开")
    )
    menus = MagicMock(player=player, query=team_query)
    menus.open = AsyncMock()

    await resource.handle_team_resource(
        cast("Matcher", object()),
        event,
        service,
        menus,
    )

    service.query_overview.assert_awaited_once_with(
        TeamResourceSubscriptionTarget("group", GROUP_ID),
        first_team_id=None,
    )
    menus.open.assert_awaited_once()


@pytest.mark.asyncio
async def test_team_resource_admin_without_mentions_subscribes_self(
    monkeypatch: MonkeyPatch,
) -> None:
    event = group_message_event(
        f"订阅战队{TEAM_ID} {TEAM_THRESHOLD}",
        user_id=123,
        sender={"role": "admin"},
    )
    service = MagicMock()
    service.parse_manage.return_value = TEAM_RESOURCE_SERVICE.parse_manage(
        event.get_plaintext()
    )
    service.allows_target.return_value = True
    service.add_target_subscription = AsyncMock(return_value="已订阅")
    finish = AsyncMock()
    monkeypatch.setattr(resource, "finish_event_reply", finish)

    await resource.handle_team_resource_manage(
        cast("Matcher", object()),
        event,
        service,
        cast("Any", object()),
    )

    call = service.add_target_subscription.await_args
    assert call is not None
    assert call.kwargs["target"] == TeamResourceSubscriptionTarget(
        "group",
        GROUP_ID,
        (123,),
    )


@pytest.mark.asyncio
async def test_team_resource_manage_rule_allows_manual_mentions_and_replies() -> None:
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

    assert resource._at_user_ids_from_event(event) == (234,)
    matcher = _team_resource_matcher("team_resource_manage")
    assert await matcher.rule(
        cast("Bot", None),
        event,
        {},
    )
    assert await matcher.rule(
        cast("Bot", None),
        replied_event,
        {},
    )


@pytest.mark.asyncio
async def test_team_resource_private_rules_allow_enabled_user() -> None:
    runtime = build_test_runtime(
        feature_config=FeatureConfig(
            user_policy={"123": ["team_resource_subscription"]},
        )
    )
    service = TeamResourceService(
        TeamResourceConfig(),
        TeamResourceSubscriptionStore(":memory:"),
        HEADLESS,
        OneBotReferenceResolver({}, {}),
        runtime.features,
        runtime.delivery,
    )
    registry = runtime.matcher_registry()
    resource.install(registry, service, MagicMock(), MagicMock())
    manage = next(
        matcher
        for matcher in registry.message_matchers
        if registry.cooldown_registration(matcher)
        == ("command", "team_resource_manage")
    )
    query = next(
        matcher
        for matcher in registry.message_matchers
        if registry.cooldown_registration(matcher) == ("command", "team_resource_query")
    )

    assert await manage.rule(
        cast("Bot", None),
        private_message_event(f"订阅战队{TEAM_ID}", user_id=123),
        {},
    )
    assert await query.rule(
        cast("Bot", None),
        private_message_event("战队", user_id=123),
        {},
    )


@pytest.mark.asyncio
async def test_team_resource_notice_leaves_bot_selection_to_router(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = TeamResourceConfig()
    store = TeamResourceSubscriptionStore(tmp_path / "qq_state.sqlite")
    store.upsert(
        TeamResourceSubscriptionUpdate(
            group_id=GROUP_ID,
            team_id=TEAM_ID,
            team_name="示例战队",
            threshold=1000,
            at_user_ids=(),
            operator_id=1,
        )
    )
    service = TeamResourceService(
        config,
        store,
        HEADLESS,
        OneBotReferenceResolver(group_aliases={}, user_aliases={}),
        TEST_RUNTIME.features,
        TEST_RUNTIME.delivery,
    )
    sent: list[tuple[list[MessageTarget], str | Message, dict[str, object]]] = []

    async def fake_query(
        _self: TeamResourceService,
        team_id: int,
        *,
        group_id: int | None = None,
    ) -> TeamResourceResult:
        assert team_id == TEAM_ID
        assert group_id == GROUP_ID
        return TeamResourceResult(TEAM_ID, "示例战队", "", 500)

    async def fake_send_target_messages(
        _delivery: object,
        target_messages: list[tuple[MessageTarget, str | Message]],
        **kwargs: object,
    ) -> TargetSendSummary:
        sent.extend(
            ([target], message, kwargs) for target, message in target_messages
        )
        return TargetSendSummary(
            [target for target, _message in target_messages],
            [],
        )

    monkeypatch.setattr(TeamResourceService, "query", fake_query)
    monkeypatch.setattr(
        OneBotDelivery,
        "send_target_messages",
        fake_send_target_messages,
    )

    await service.scan()

    assert sent[0][0] == [MessageTarget("group", 456)]
    assert "bot" not in sent[0][2]
