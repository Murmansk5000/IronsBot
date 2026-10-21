from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.portable_commands import PortableCommandRouter

if TYPE_CHECKING:
    from ironsbot.core.platform import ConversationKind


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "kind,source", [("group", "user"), ("private", "user"), ("group", "group")]
)
@pytest.mark.parametrize("admin", [False, True])
async def test_shared_blacklist_silently_consumes_input_before_side_effects(
    platform: Platform, kind: ConversationKind, source: str, *, admin: bool
) -> None:
    actor = ActorRef(platform, "member")
    conversation = ConversationRef(platform, kind, "conversation")
    context = MessageInputContext(
        IncomingMessageRef(platform, actor, conversation, "message", "执行"),
        mentions_bot=True,
    )
    grants = frozenset({"blacklist"})
    features = FeatureService(
        {conversation: grants} if source == "group" else {},
        {actor: grants} if source == "user" else {},
        frozenset({actor}) if admin else frozenset(),
    )
    claims = Mock(claim=AsyncMock(side_effect=RuntimeError("storage failure")))
    observer = Mock(observe_official_message=AsyncMock())
    union = Mock(observe=AsyncMock())
    ai = Mock(chat_reply=AsyncMock())
    send = AsyncMock()
    catalog = CommandCatalog()
    router = PortableCommandRouter(
        catalog,
        {},
        features,
        ai=ai,
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        inbound_claims=claims,
        identity_observer=observer,
        union_identity=union,
    )
    assert await router.ingress.handle(context, send)
    claims.claim.assert_not_awaited()
    observer.observe_official_message.assert_not_awaited()
    union.observe.assert_not_awaited()
    ai.chat_reply.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_blacklist_is_rechecked_after_identity_preparation() -> None:
    platform = Platform.QQ_OFFICIAL
    actor = ActorRef(platform, "member")
    conversation = ConversationRef(platform, "group", "group")
    context = MessageInputContext(
        IncomingMessageRef(platform, actor, conversation, "message", "执行"),
        mentions_bot=True,
    )
    user_policies: dict[ActorRef, frozenset[str]] = {}
    features = FeatureService({}, user_policies, frozenset())

    async def observe(_incoming: IncomingMessageRef) -> None:
        user_policies[actor] = frozenset({"blacklist"})

    union = Mock(observe=AsyncMock(side_effect=observe))
    claims = Mock(claim=AsyncMock(return_value=True))
    ai = Mock(chat_reply=AsyncMock())
    send = AsyncMock()
    catalog = CommandCatalog()
    router = PortableCommandRouter(
        catalog,
        {},
        features,
        ai=ai,
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        inbound_claims=claims,
        union_identity=union,
    )
    assert await router.ingress.handle(context, send)
    union.observe.assert_awaited_once()
    claims.claim.assert_awaited_once()
    ai.chat_reply.assert_not_awaited()
    send.assert_not_awaited()
