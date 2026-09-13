from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.config.models.features import FeatureConfig
from ironsbot.config.models.operations import HeadlessConfig, HeadlessNoticeConfig
from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.integrations.storage.team_resources import TeamResourceSubscriptionStore
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.team.resource import (
    TeamResourceResult,
    TeamResourceService,
)
from ironsbot.services.team.resource_commands import team_resource_command_contracts
from ironsbot.services.team.resource_subscriptions import (
    TeamResourcePrivateSubscriptionUpdate,
    TeamResourceSubscriptionTarget,
    TeamResourceSubscriptionUpdate,
)
from tests.helpers.onebot_events import group_message_event, private_message_event
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot
    from nonebot.matcher import Matcher

    from ironsbot.core.feature_policy import FeatureService

os.environ["APP_CONFIG_PATH"] = str(
    Path(__file__).resolve().parents[1] / "config.example.toml"
)

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.onebot import team_resource as resource

TEAM_ID = 1234567
TEAM_THRESHOLD = 2000
GROUP_ID = 456
OWNER_ID = 123
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


def _actor(user_id: int) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


def _group(group_id: int = GROUP_ID) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


@dataclass
class FakeTeamResourceNoticeSender:
    sent: list[tuple[TeamResourceSubscriptionTarget, str]] = field(
        default_factory=list,
    )

    async def send_low_resource_notice(
        self,
        target: TeamResourceSubscriptionTarget,
        message: str,
    ) -> bool:
        self.sent.append((target, message))
        return True


def _service(
    config: TeamResourceConfig,
    state_path: Path = Path("data/state/qq_state.sqlite"),
    *,
    sender: FakeTeamResourceNoticeSender | None = None,
    features: FeatureService | None = None,
) -> TeamResourceService:
    return TeamResourceService(
        config,
        TeamResourceSubscriptionStore(state_path),
        HEADLESS,
        features or TEST_RUNTIME.features,
        sender or FakeTeamResourceNoticeSender(),
    )


TEAM_RESOURCE_REGISTRY = TEST_RUNTIME.matcher_factory()
TEAM_RESOURCE_SERVICE = _service(TeamResourceConfig())
resource.install(TEAM_RESOURCE_REGISTRY, TEAM_RESOURCE_SERVICE)


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
        TeamResourceConfig(enabled=True, times=["22:30:15", "23:45"])
    )

    service.register_jobs(scheduler)

    scan = scheduler.jobs[0]["func"]
    assert scheduler.jobs == [
        {
            "func": scan,
            "trigger": "cron",
            "id": "team_resource_scan_223015",
            "replace_existing": True,
            "hour": 22,
            "minute": 30,
            "second": 15,
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
    _service(TeamResourceConfig(enabled=False, times=["23:00"])).register_jobs(
        scheduler
    )

    assert scheduler.jobs == []


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("commands", [[], ["资源查询", "本群资源"]])
def test_team_config_keeps_catalog_and_matcher_registration_in_sync(
    tmp_path: Path, *, enabled: bool, commands: list[str]
) -> None:
    config = TeamResourceConfig(enabled=enabled, commands=commands)
    service = _service(config, state_path=tmp_path / "qq.sqlite")
    registry = TEST_RUNTIME.matcher_factory()
    resource.install(registry, service)
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="team_resource",
                commands=team_resource_command_contracts(
                    enabled=service.enabled, query_commands=service.query_commands
                ),
            ),
        ),
        known_features={"team_resource_subscription"},
    )
    registry.validate_command_catalog(catalog)
    assert len(registry.message_matchers) == (2 + bool(commands) if enabled else 0)
    context = CommandContext(_actor(OWNER_ID), _group())
    target = TeamResourceSubscriptionTarget(_group())
    for text in ("资源查询", "本群资源", "战队"):
        expected = enabled and text in commands
        assert (
            catalog.claims_direct_input(context, TEST_RUNTIME.features, text)
            is expected
        )
        assert (
            service.matches_target_query(text, actor=context.actor, target=target)
            is expected
        )


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
    ) == ("command", "team_resource_manage")


@pytest.mark.asyncio
async def test_team_resource_manage_rule_reads_direct_member_mentions() -> None:
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

    assert resource._mention_actors_from_event(event) == (_actor(234),)
    matcher = _team_resource_matcher("team_resource_manage")
    assert await matcher.rule(cast("Bot", None), event, {})
    assert await matcher.rule(cast("Bot", None), replied_event, {})


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
        runtime.features,
        FakeTeamResourceNoticeSender(),
    )
    registry = runtime.matcher_factory()
    resource.install(registry, service)
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
async def test_team_resource_notice_uses_typed_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sender = FakeTeamResourceNoticeSender()
    store = TeamResourceSubscriptionStore(tmp_path / "qq_state.sqlite")
    store.upsert(
        TeamResourceSubscriptionUpdate(
            conversation=_group(),
            team_id=TEAM_ID,
            team_name="示例战队",
            threshold=1000,
            mention_actors=(),
            operator=_actor(1),
        )
    )
    service = TeamResourceService(
        TeamResourceConfig(),
        store,
        HEADLESS,
        TEST_RUNTIME.features,
        sender,
    )

    async def fake_query(
        _self: TeamResourceService,
        team_id: int,
    ) -> TeamResourceResult:
        assert team_id == TEAM_ID
        return TeamResourceResult(TEAM_ID, "示例战队", "", 500)

    monkeypatch.setattr(TeamResourceService, "query", fake_query)

    await service.scan()

    assert sender.sent == [
        (
            TeamResourceSubscriptionTarget(_group()),
            "查到了战队 示例战队（1234567）资源是 500，低于阈值 1000。\n"
            "出来买资源，别逼我求你😡",
        )
    ]


@pytest.mark.asyncio
async def test_team_resource_scan_keeps_private_superuser_bypass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sender = FakeTeamResourceNoticeSender()
    runtime = build_test_runtime(
        feature_config=FeatureConfig(superuser_bypass=True),
        superuser_ids=(OWNER_ID,),
    )
    service = _service(
        TeamResourceConfig(enabled=True),
        tmp_path / "team-resource.sqlite",
        sender=sender,
        features=runtime.features,
    )
    service._store.upsert_private(
        TeamResourcePrivateSubscriptionUpdate(
            actor=_actor(OWNER_ID),
            team_id=TEAM_ID,
            team_name="示例战队",
            threshold=1000,
        )
    )

    async def fake_query(
        _self: TeamResourceService,
        team_id: int,
    ) -> TeamResourceResult:
        assert team_id == TEAM_ID
        return TeamResourceResult(TEAM_ID, "示例战队", "", 500)

    monkeypatch.setattr(TeamResourceService, "query", fake_query)

    await service.scan()

    assert sender.sent[0][0] == TeamResourceSubscriptionTarget(_actor(OWNER_ID))


@pytest.mark.asyncio
async def test_default_mentions_do_not_cross_platforms(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = TeamResourceSubscriptionStore(tmp_path / "qq_state.sqlite")
    service = TeamResourceService(
        TeamResourceConfig(),
        store,
        HEADLESS,
        TEST_RUNTIME.features,
        FakeTeamResourceNoticeSender(),
        (_actor(OWNER_ID),),
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "official-group",
    )
    operator = ActorRef(
        Platform.QQ_OFFICIAL,
        "official-owner",
        "member",
        conversation.id,
    )

    async def fake_query(
        _self: TeamResourceService,
        team_id: int,
    ) -> TeamResourceResult:
        return TeamResourceResult(team_id, "示例战队", "", 500)

    monkeypatch.setattr(TeamResourceService, "query", fake_query)

    await service.add_target_subscription(
        target=TeamResourceSubscriptionTarget(conversation),
        team_id=TEAM_ID,
        threshold=None,
        operator=operator,
    )

    assert store.list_conversation(conversation)[0].mention_actors == ()
