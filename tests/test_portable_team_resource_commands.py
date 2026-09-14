from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.command_catalog import CommandCatalog, command_context_from_input
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.features import Feature
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_team_resource_commands import (
    build_portable_team_overview_operation,
    build_portable_team_resource_operations,
)
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.team import PlayerTeamLookup
from ironsbot.services.team.resource import TeamOverviewItem
from ironsbot.services.team.resource_commands import team_resource_command_contracts
from ironsbot.services.team.resource_subscriptions import (
    TeamResourceManageCommand,
    TeamResourceSubscriptionTarget,
    parse_team_resource_manage_command,
)

if TYPE_CHECKING:
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.seer.team import SeerTeamQueryService
    from ironsbot.services.team.resource import TeamResourceService


@dataclass
class _Service:
    targets: list[TeamResourceSubscriptionTarget] = field(default_factory=list)
    additions: list[
        tuple[TeamResourceSubscriptionTarget, int, int | None, ActorRef]
    ] = field(default_factory=list)
    removals: list[tuple[TeamResourceSubscriptionTarget, int]] = field(
        default_factory=list
    )
    query_messages: list[str] = field(default_factory=lambda: ["战队一", "战队二"])
    allowed: bool = True
    first_team_ids: list[int | None] = field(default_factory=list)

    def allows_target(
        self, _actor: ActorRef, _target: TeamResourceSubscriptionTarget
    ) -> bool:
        return self.allowed

    async def query_overview(
        self,
        target: TeamResourceSubscriptionTarget,
        *,
        first_team_id: int | None = None,
    ) -> tuple[TeamOverviewItem, ...]:
        self.targets.append(target)
        self.first_team_ids.append(first_team_id)
        return tuple(
            TeamOverviewItem(123456 + index, text, "人数：42｜资源：100")
            for index, text in enumerate(self.query_messages)
        )

    def subscriptions_message(self, target: TeamResourceSubscriptionTarget) -> str:
        self.targets.append(target)
        return "订阅列表"

    @staticmethod
    def parse_manage(text: str) -> TeamResourceManageCommand | None:
        return parse_team_resource_manage_command(text)

    async def add_target_subscription(
        self,
        *,
        target: TeamResourceSubscriptionTarget,
        team_id: int,
        threshold: int | None,
        operator: ActorRef,
    ) -> str:
        self.additions.append((target, team_id, threshold, operator))
        return "订阅成功"

    def remove_target_subscription(
        self,
        *,
        target: TeamResourceSubscriptionTarget,
        team_id: int,
    ) -> str:
        self.removals.append((target, team_id))
        return "取消成功"


GROUP = ConversationRef(Platform.QQ_OFFICIAL, "group", "group-openid")
ACTOR = ActorRef(Platform.QQ_OFFICIAL, "actor-openid", "member", GROUP.id)
MENTIONED = ActorRef(Platform.QQ_OFFICIAL, "target-openid", "member", GROUP.id)


def _context(
    text: str,
    *,
    private: bool = False,
    mentions: tuple[ActorRef, ...] = (),
    group_role: str | None = None,
) -> MessageInputContext:
    actor = ActorRef(Platform.QQ_OFFICIAL, ACTOR.id) if private else ACTOR
    conversation = (
        ConversationRef(Platform.QQ_OFFICIAL, "private", actor.id) if private else GROUP
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=conversation,
            message_id="event-id",
            text=text,
            direct_mentions=mentions,
            group_role=group_role,
        ),
        mentions_bot=False,
    )


def _text(message: object) -> str:
    assert isinstance(message, OutboundMessage)
    part = message.parts[0]
    assert isinstance(part, TextPart)
    return part.text


def _operations(service: _Service):
    typed_service = cast("TeamResourceService", service)
    return build_portable_team_resource_operations(
        typed_service,
        query=build_portable_team_overview_operation(
            typed_service,
            cast("SeerTeamQueryService", AsyncMock()),
            PlayerIdResolver(lambda _ref, _conv: None, lambda _actor: None),
            FeatureService({}, {}, frozenset()),
            PortableQuerySessions(),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("bound_id", [None, 700001])
async def test_overview_uses_actor_binding_and_shared_numeric_session(
    *, private: bool, bound_id: int | None
) -> None:
    service = _Service()
    teams = AsyncMock()
    teams.lookup_player_team.return_value = PlayerTeamLookup(team_id=123456)
    teams.query.return_value = "战队详情"
    sessions = PortableQuerySessions()
    context = _context("战队", private=private)
    bindings = []

    def binding(actor: ActorRef) -> int | None:
        bindings.append(actor)
        return bound_id

    operation = build_portable_team_overview_operation(
        cast("TeamResourceService", service),
        cast("SeerTeamQueryService", teams),
        PlayerIdResolver(lambda _ref, _conv: None, binding),
        FeatureService({}, {}, frozenset()),
        sessions,
    )
    response = await operation(context.text, context)
    assert "战队一" in _text(response)
    assert bindings == [context.message.actor]
    assert service.first_team_ids == [123456 if bound_id else None]
    if bound_id:
        assert teams.lookup_player_team.await_args.args[0] == bound_id
    else:
        teams.lookup_player_team.assert_not_awaited()
    assert sessions.recognizes_response("1", context)
    assert not sessions.recognizes_response("战队一", context)
    assert _text(await sessions.select("2", context)) == "战队详情"
    assert teams.query.await_args.args[0] == (123457,)
    assert teams.query.await_args.args[1].actor == context.message.actor
    service.allowed = False
    assert "未对你开放" in _text(await sessions.select("1", context))
    teams.query.assert_awaited_once()
    assert "退出" in _text(await sessions.select("0", context))
    assert not sessions.has_pending(context)


@pytest.mark.asyncio
@pytest.mark.parametrize("has_subscriptions", [False, True])
async def test_bound_lookup_failure_preserves_subscriptions(
    *, has_subscriptions: bool
) -> None:
    service = _Service(query_messages=["订阅战队"] if has_subscriptions else [])
    teams = AsyncMock()
    teams.lookup_player_team.return_value = PlayerTeamLookup(error="所属战队查询超时")
    sessions = PortableQuerySessions()
    context = _context("战队", private=True)
    operation = build_portable_team_overview_operation(
        cast("TeamResourceService", service),
        cast("SeerTeamQueryService", teams),
        PlayerIdResolver(lambda _ref, _conv: None, lambda _actor: 700001),
        FeatureService({}, {}, frozenset()),
        sessions,
    )
    response = _text(await operation(context.text, context))
    assert "所属战队查询超时" in response
    assert ("订阅战队" in response) is has_subscriptions
    assert sessions.has_pending(context) is has_subscriptions


@pytest.mark.asyncio
async def test_overview_denial_does_not_fetch_or_open_menu() -> None:
    service = _Service(allowed=False)
    teams = AsyncMock()
    sessions = PortableQuerySessions()
    context = _context("战队")
    operation = build_portable_team_overview_operation(
        cast("TeamResourceService", service),
        cast("SeerTeamQueryService", teams),
        PlayerIdResolver(lambda _ref, _conv: None, lambda _actor: 700001),
        FeatureService({}, {}, frozenset()),
        sessions,
    )
    assert "未对你开放" in _text(await operation(context.text, context))
    teams.lookup_player_team.assert_not_awaited()
    assert not service.targets
    assert not sessions.has_pending(context)


@pytest.mark.parametrize(
    ("mentions", "expected"),
    [((), "team_resource.query"), ((MENTIONED,), "seer.team.query")],
)
def test_team_catalog_assigns_bare_and_member_target_to_one_owner(
    mentions: tuple[ActorRef, ...], expected: str
) -> None:
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="seer_query",
                commands=seer_command_contracts(
                    PlayerIdResolver(lambda _ref, _conv: None, lambda _actor: None)
                ),
            ),
            PluginContribution(
                id="team_resource",
                commands=team_resource_command_contracts(
                    enabled=True, query_commands=("战队",)
                ),
            ),
        ),
        known_features={feature.value for feature in Feature},
    )
    context = command_context_from_input(_context("战队", mentions=mentions))
    features = FeatureService(
        {GROUP: frozenset({"seer_team", "team_resource_subscription"})},
        {},
        frozenset(),
    )
    assert [
        command.id
        for command in catalog.available_for_context(context, features)
        if command.matches_direct_input(context, "战队")
    ] == [expected]


@pytest.mark.asyncio
async def test_group_query_reuses_subscribed_team_service() -> None:
    service = _Service()
    operations = _operations(service)

    result = await operations["team_resource.query"]("战队", _context("战队"))

    assert "战队一" in _text(result) and "战队二" in _text(result)
    assert "资源：100" in _text(result)
    assert service.targets == [TeamResourceSubscriptionTarget(GROUP)]


@pytest.mark.asyncio
async def test_group_subscription_keeps_typed_platform_mentions() -> None:
    service = _Service()
    operations = _operations(service)
    context = _context(
        "订阅战队1234567 2000",
        mentions=(MENTIONED,),
    )

    result = await operations["team_resource.subscribe"](context.text, context)

    assert _text(result) == "订阅成功"
    assert service.additions == [
        (
            TeamResourceSubscriptionTarget(GROUP, (MENTIONED,)),
            1234567,
            2000,
            ACTOR,
        )
    ]


@pytest.mark.asyncio
async def test_manual_at_text_is_not_treated_as_a_structured_identity() -> None:
    service = _Service()
    operations = _operations(service)
    context = _context("订阅战队1234567 @123456")

    result = await operations["team_resource.subscribe"](context.text, context)

    assert "@ 选人功能" in _text(result)
    assert service.additions == []


@pytest.mark.asyncio
async def test_private_subscription_is_owned_by_the_actor() -> None:
    service = _Service()
    operations = _operations(service)
    context = _context("订阅战队1234567", private=True)

    await operations["team_resource.subscribe"](context.text, context)

    assert service.additions[0][0] == TeamResourceSubscriptionTarget(
        context.message.actor
    )


@pytest.mark.asyncio
async def test_remove_and_empty_query_reuse_subscription_state() -> None:
    service = _Service(query_messages=[])
    operations = _operations(service)
    context = _context("取消订阅战队1234567")

    removed = await operations["team_resource.unsubscribe"](context.text, context)
    queried = await operations["team_resource.query"]("战队", _context("战队"))

    assert _text(removed) == "取消成功"
    assert _text(queried) == "订阅列表"
    assert service.removals == [(TeamResourceSubscriptionTarget(GROUP), 1234567)]


@pytest.mark.asyncio
async def test_catalog_limits_subscribe_to_group_managers() -> None:
    service = _Service()
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="team_resource",
                commands=team_resource_command_contracts(
                    enabled=True,
                    query_commands=("战队",),
                ),
            ),
        ),
        known_features={"team_resource_subscription"},
    )
    features = FeatureService(
        {GROUP: frozenset({"team_resource_subscription"})},
        {},
        frozenset(),
    )
    router = PortableCommandRouter(
        catalog,
        _operations(service),
        features,
        ai=cast("AiService", object()),
    )

    member_reply = await router.dispatch(_context("订阅战队1234567"))
    manager_reply = await router.dispatch(
        _context("订阅战队1234567", group_role="admin")
    )

    assert member_reply is None
    assert manager_reply is not None
    assert _text(manager_reply.message) == "订阅成功"
