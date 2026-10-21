# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, SendResult, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.identity.player_accounts import (
    PlayerAccount,
    PlayerAccountRegistry,
)
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_rank_commands import build_portable_rank_operations
from ironsbot.services.portable_reply import deliver_portable_reply
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts
from ironsbot.services.seer.rank_list_models import RankPlayerCommand
from ironsbot.services.seer.rank_queries import RankPlayerPreparedReply

PLAYER_ID = 712_345_678
PRIVATE_GROUP_ID = 987_654_321


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("target", ["alias", "member", "mixed", "outside_group"])
async def test_public_rank_resolves_scoped_alias_and_member_without_mixing(
    platform: Platform, target: str
) -> None:
    private_group = ConversationRef(platform, "group", str(PRIVATE_GROUP_ID))
    conversation = (
        ConversationRef(platform, "group", "another-group")
        if target == "outside_group"
        else private_group
    )
    accounts = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=PLAYER_ID,
                name="sample_player",
                aliases=("示例玩家",),
                password=None,
                public=False,
            ),
        ),
        private_alias_groups={private_group: ("sample_player",)},
    )
    resolver = PlayerIdResolver(
        lambda reference, group: accounts.resolve_player_id(
            reference, conversation=group
        ),
        lambda actor: PLAYER_ID if actor.id == "456" else None,
    )
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "123"),
            conversation,
            "1",
            "群星牌榜" if target == "member" else "成就榜示例玩家",
            direct_mentions=(ActorRef(platform, "456"),)
            if target in {"member", "mixed"}
            else (),
        ),
        mentions_bot=True,
    )
    features = FeatureService({conversation: frozenset({"seer_rank"})}, {}, frozenset())
    charged = Mock()
    service = Mock(
        default_limit=Mock(return_value=10),
        prepare_player=AsyncMock(
            return_value=RankPlayerPreparedReply("rank result", on_delivered=charged)
        ),
    )
    sessions = PortableQuerySessions()
    operations = build_portable_rank_operations(
        service, resolver, sessions, AsyncMock(), features
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="rank_help",
                commands=tuple(
                    command
                    for command in rank_help_command_contracts(resolver)
                    if command.id in operations
                ),
            ),
        ),
        known_features=("seer_rank",),
    )
    router = PortableCommandRouter(
        catalog,
        operations,
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
        query_sessions=sessions,
    )
    reply = await router.dispatch(context)
    if target == "outside_group":
        assert reply is None
        service.prepare_player.assert_not_awaited()
        charged.assert_not_called()
        return
    assert reply is not None
    if target == "mixed":
        assert "不能同时使用" in "".join(
            part.text for part in reply.message.parts if isinstance(part, TextPart)
        )
        service.prepare_player.assert_not_awaited()
        charged.assert_not_called()
        return
    service.prepare_player.assert_awaited_once_with(
        RankPlayerCommand("群星牌" if target == "member" else "成就点数", PLAYER_ID),
        actor=context.message.actor,
        conversation=conversation,
    )
    assert reply.message == OutboundMessage.from_text("rank result")
    charged.assert_not_called()
    await deliver_portable_reply(
        reply, AsyncMock(return_value=SendResult(delivered=True, message_id="receipt"))
    )
    charged.assert_called_once()
