from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_team_resource_commands import (
    build_portable_team_resource_operations,
)
from ironsbot.services.team.resource_commands import team_resource_command_contracts
from ironsbot.services.team.resource_subscriptions import (
    TeamResourceManageCommand,
    TeamResourceSubscriptionTarget,
    parse_team_resource_manage_command,
)

if TYPE_CHECKING:
    from ironsbot.services.ai.service import AiService
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

    async def query_target_messages(
        self,
        target: TeamResourceSubscriptionTarget,
    ) -> list[str]:
        self.targets.append(target)
        return self.query_messages

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
        ConversationRef(Platform.QQ_OFFICIAL, "private", actor.id)
        if private
        else GROUP
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


@pytest.mark.asyncio
async def test_group_query_reuses_subscribed_team_service() -> None:
    service = _Service()
    operations = build_portable_team_resource_operations(
        cast("TeamResourceService", service)
    )

    result = await operations["team_resource.query"]("战队", _context("战队"))

    assert _text(result) == "战队一\n\n战队二"
    assert service.targets == [TeamResourceSubscriptionTarget(GROUP)]


@pytest.mark.asyncio
async def test_group_subscription_keeps_typed_platform_mentions() -> None:
    service = _Service()
    operations = build_portable_team_resource_operations(
        cast("TeamResourceService", service)
    )
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
    operations = build_portable_team_resource_operations(
        cast("TeamResourceService", service)
    )
    context = _context("订阅战队1234567 @123456")

    result = await operations["team_resource.subscribe"](context.text, context)

    assert "@ 选人功能" in _text(result)
    assert service.additions == []


@pytest.mark.asyncio
async def test_private_subscription_is_owned_by_the_actor() -> None:
    service = _Service()
    operations = build_portable_team_resource_operations(
        cast("TeamResourceService", service)
    )
    context = _context("订阅战队1234567", private=True)

    await operations["team_resource.subscribe"](context.text, context)

    assert service.additions[0][0] == TeamResourceSubscriptionTarget(
        context.message.actor
    )


@pytest.mark.asyncio
async def test_remove_and_empty_query_reuse_subscription_state() -> None:
    service = _Service(query_messages=[])
    operations = build_portable_team_resource_operations(
        cast("TeamResourceService", service)
    )
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
        build_portable_team_resource_operations(
            cast("TeamResourceService", service)
        ),
        features,
        ai=cast("AiService", object()),
        addressed_input_hints=AddressedInputHintService(),
    )

    member_reply = await router.dispatch(_context("订阅战队1234567"))
    manager_reply = await router.dispatch(
        _context("订阅战队1234567", group_role="admin")
    )

    assert member_reply is None
    assert manager_reply is not None
    assert _text(manager_reply.message) == "订阅成功"
