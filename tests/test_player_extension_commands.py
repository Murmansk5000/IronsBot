from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.services.operations.request_feedback import send_request_feedback
from ironsbot.services.player_extension_commands import (
    build_player_extension_operation,
    query_player_extension,
)
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailActionRequest,
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_result import QueryReply

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("role", ["member", "admin", "owner"])
@pytest.mark.parametrize("reference", ["", "700001", "别名"])
@pytest.mark.parametrize("queued", [None, False, True])
async def test_extensions_use_one_typed_request_and_delivery_template(
    platform: Platform,
    role: str,
    reference: str,
    *,
    queued: bool | None,
) -> None:
    actor = ActorRef(platform, "member-a")
    conversation = ConversationRef(platform, "group", "group-a")
    context = MessageInputContext(
        IncomingMessageRef(
            platform=platform,
            actor=actor,
            conversation=conversation,
            message_id="message-a",
            text=f"档案{reference}",
            group_role=role,
        ),
        mentions_bot=True,
    )
    result = QueryReply(text="detail", image=b"image-bytes")

    async def query(_request: PlayerDetailActionRequest) -> QueryReply:
        if queued is not None:
            await send_request_feedback(queued=queued)
        return result

    query_mock = AsyncMock(side_effect=query)
    action = PlayerDetailExtensionAction(
        id="sample_detail",
        feature="seer_player",
        label="档案",
        aliases=("档案",),
        command_help_id="sample.detail",
        query=query_mock,
        action=ActionDefinition("sample_detail", "档案"),
    )
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(action)
    features = cast(
        "FeatureService",
        SimpleNamespace(
            is_feature_allowed=lambda *_: True,
            is_actor_superuser=lambda _: False,
        ),
    )
    resolver = PlayerIdResolver(lambda *_: 700001, lambda _: 700001)
    operation = build_player_extension_operation(extensions, resolver, features)
    reply = await operation(context.text, context)
    assert isinstance(reply, PortableReply)
    query_mock.assert_awaited_once_with(
        PlayerDetailActionRequest(
            700001,
            actor,
            conversation,
            can_manage=role in {"admin", "owner"},
        )
    )
    if queued is None:
        assert reply.follow_up is None
        assert reply.message == result.to_outbound()
    else:
        assert reply.follow_up is not None
        reply.delivered()
        assert await reply.follow_up() == result.to_outbound()


@pytest.mark.asyncio
async def test_extension_policy_is_rechecked_when_action_is_executed() -> None:
    actor = ActorRef(Platform.QQ_OFFICIAL, "member-a")
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "group", "group-a")
    context = MessageInputContext(
        IncomingMessageRef(
            platform=actor.platform,
            actor=actor,
            conversation=conversation,
            message_id="message-a",
            text="档案",
        ),
        mentions_bot=True,
    )
    query = AsyncMock(return_value=QueryReply(text="private detail"))
    action = PlayerDetailExtensionAction(
        id="sample_detail",
        feature="seer_player",
        label="档案",
        aliases=("档案",),
        command_help_id="sample.detail",
        query=query,
        action=ActionDefinition("sample_detail", "档案"),
    )
    features = cast(
        "FeatureService", SimpleNamespace(is_feature_allowed=lambda *_: False)
    )
    reply = await query_player_extension(action, 700001, context, features)
    assert reply.message == QueryReply(text="该功能当前未对你开放。").to_outbound()
    query.assert_not_awaited()
