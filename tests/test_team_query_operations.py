from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.player_references import PlayerReferenceChoice
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_commands import team_query_input_matcher
from ironsbot.services.seer.team import SeerTeamQueryService, TeamQueryActor
from ironsbot.services.seer.team_commands import build_team_query_operation


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("text", ["战队示例", "战队米米号示例", "战队90001 90002"])
async def test_team_operation_preserves_id_kind_and_selects_player_targets(
    platform: Platform,
    text: str,
) -> None:
    service = Mock()
    service.query = AsyncMock(return_value="team")
    service.query_player_team = AsyncMock(return_value="player team")
    service.parse_team_ids = SeerTeamQueryService.parse_team_ids
    sessions = PortableQuerySessions()
    resolver = PlayerIdResolver(
        lambda reference, _conversation: (
            int(reference) if reference.isdecimal() else None
        ),
        lambda _actor: None,
        reference_search=lambda _reference, _actor, _conversation: (
            PlayerReferenceChoice(90001, "示例甲"),
            PlayerReferenceChoice(90002, "示例乙"),
        ),
    )
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "actor"),
            ConversationRef(platform, "group", "group"),
            "message",
            text,
        ),
        mentions_bot=True,
    )
    assert team_query_input_matcher(resolver.has_reference_choices)(
        text,
        command_context_from_input(context),
    )
    operation = build_team_query_operation(
        cast("SeerTeamQueryService", service),
        resolver,
        FeatureService({}, {}, frozenset()),
        sessions,
    )
    reply = await operation(text, context)
    assert isinstance(reply, OutboundMessage)
    actor = TeamQueryActor(
        context.message.actor,
        context.message.conversation,
        can_manage=False,
    )
    if text == "战队90001 90002":
        service.query.assert_awaited_once_with((90001, 90002), actor)
        service.query_player_team.assert_not_awaited()
        assert sessions.active_prompt(context) is None
    else:
        service.query_player_team.assert_not_awaited()
        service.query.assert_not_awaited()
        assert sessions.active_prompt(context) is not None
        await sessions.select("2", context)
        service.query_player_team.assert_awaited_once_with(90002, actor)
