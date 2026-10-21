from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.config.models.features import FeatureConfig
from ironsbot.config.models.messaging import (
    CommandCooldownConfig,
    CommandCooldownWindowConfig,
)
from ironsbot.config.models.operations import HeadlessConfig, HeadlessNoticeConfig
from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.outbound import SendResult
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.headless_seer.client import ClientManager
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.storage.team_resources import TeamResourceSubscriptionStore
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import deliver_portable_reply
from ironsbot.services.portable_team_resource_commands import (
    build_portable_team_resource_operations,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolution
from ironsbot.services.team.resource import (
    TeamResourceQueryError,
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
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.team import SeerTeamQueryService

os.environ["APP_CONFIG_PATH"] = str(
    Path(__file__).resolve().parents[1] / "config.example.toml"
)

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

TEAM_ID = 1234567
SECOND_TEAM_ID = 1234568
TEAM_MEMBER_COUNT = 60
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


TEAM_RESOURCE_SERVICE = _service(TeamResourceConfig())


def _catalog(service: TeamResourceService) -> CommandCatalog:
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
    return catalog


def _router(
    service: TeamResourceService,
    features: FeatureService,
    sessions: PortableQuerySessions | None = None,
) -> PortableCommandRouter:
    sessions = sessions or PortableQuerySessions()
    catalog = _catalog(service)
    operations = build_portable_team_resource_operations(
        service,
        cast(
            "PlayerIdResolver",
            Mock(
                resolve=Mock(return_value=PlayerIdResolution(None, offer_binding=False))
            ),
        ),
        cast("SeerTeamQueryService", object()),
        sessions,
    )
    return PortableCommandRouter(
        catalog,
        {
            key: operation
            for key, operation in operations.items()
            if key in catalog.command_ids
        },
        features,
        ai=cast("AiService", object()),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )


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
    service = _service(TeamResourceConfig(enabled=True, times=["22:30:15", "23:45"]))

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
@pytest.mark.asyncio
async def test_team_config_keeps_catalog_and_shared_route_in_sync(
    tmp_path: Path, *, enabled: bool, commands: list[str]
) -> None:
    config = TeamResourceConfig(enabled=enabled, commands=commands)
    service = _service(config, state_path=tmp_path / "qq.sqlite")
    catalog = _catalog(service)
    router = _router(service, TEST_RUNTIME.features)
    assert len(catalog.command_ids) == (3 + bool(commands) if enabled else 0)
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
        reply = await router.dispatch(message_input_context(group_message_event(text)))
        assert (reply is not None) is expected
        if reply is not None:
            await deliver_portable_reply(
                reply,
                AsyncMock(return_value=SendResult(delivered=True, message_id=text)),
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


@pytest.mark.asyncio
async def test_team_resource_manage_uses_shared_command_cooldown() -> None:
    sessions = PortableQuerySessions()
    cooldown = Mock(
        wraps=CommandCooldownService(
            CommandCooldownConfig(
                enabled=True,
                windows=[
                    CommandCooldownWindowConfig(window_seconds=60, max_requests=1)
                ],
            ),
            TEST_RUNTIME.features,
        )
    )
    sessions.interactions.cooldown = cooldown
    router = _router(TEAM_RESOURCE_SERVICE, TEST_RUNTIME.features, sessions)
    for index in range(2):
        reply = await router.dispatch(
            message_input_context(group_message_event("战队订阅"))
        )
        assert reply is not None
        text = str(reply.message.parts)
        assert ("操作过于频繁" in text) is (index == 1)
        await deliver_portable_reply(
            reply,
            AsyncMock(return_value=SendResult(delivered=True, message_id=str(index))),
        )
    assert [call.kwargs["command_id"] for call in cooldown.admit.call_args_list] == [
        "team_resource.list",
        "team_resource.list",
    ]


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

    assert message_input_context(event).member_mentions == (_actor(234),)
    router = _router(TEAM_RESOURCE_SERVICE, TEST_RUNTIME.features)
    assert router.recognizes(message_input_context(event))
    assert router.recognizes(message_input_context(replied_event))


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
    router = _router(service, runtime.features)
    assert router.recognizes(
        message_input_context(private_message_event(f"订阅战队{TEAM_ID}", user_id=123))
    )
    assert router.recognizes(
        message_input_context(private_message_event("战队", user_id=123))
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
async def test_team_overview_places_bound_team_first_and_keeps_partial_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = TeamResourceSubscriptionStore(tmp_path / "qq_state.sqlite")
    for team_id in (TEAM_ID, SECOND_TEAM_ID):
        store.upsert(
            TeamResourceSubscriptionUpdate(
                conversation=_group(),
                team_id=team_id,
                team_name=f"战队{team_id}",
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
        FakeTeamResourceNoticeSender(),
    )

    async def fake_query(
        _self: TeamResourceService,
        team_id: int,
    ) -> TeamResourceResult:
        if team_id == SECOND_TEAM_ID:
            raise TeamResourceQueryError.timeout(team_id)
        return TeamResourceResult(
            team_id,
            f"战队{team_id}",
            "",
            500,
            TEAM_MEMBER_COUNT,
        )

    monkeypatch.setattr(TeamResourceService, "query", fake_query)

    items = await service.query_overview(
        TeamResourceSubscriptionTarget(_group()),
        first_team_id=SECOND_TEAM_ID,
    )

    assert [item.team_id for item in items] == [SECOND_TEAM_ID, TEAM_ID]
    assert "查询超时" in items[0].error
    assert items[1].member_count == TEAM_MEMBER_COUNT


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
