from __future__ import annotations

from dataclasses import replace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.action_categories import RequestCategory
from ironsbot.core.command_catalog import CommandAccess
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.services.player_extension_commands import query_player_extension
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.query_result import QueryReply
from tests.test_portable_player_commands import (
    _context,
    _PlayerService,
    _resolver,
    _text,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("visible", [False, True])
async def test_extension_menu_access_and_cross_member_execution_are_independent(
    platform: Platform,
    *,
    visible: bool,
) -> None:
    context = _context("米米号700002", platform=platform)
    actor = context.message.actor
    conversation = context.message.conversation
    query = AsyncMock(return_value=QueryReply(text="details"))
    action = PlayerDetailExtensionAction(
        id="test.details",
        feature="seer_player",
        label="详细资料",
        aliases=("详细资料",),
        command_help_id="test.details",
        query=query,
        action=ActionDefinition(
            "test.details", "详细资料", category=RequestCategory.TAOMEE
        ),
        access=(CommandAccess(audience="superuser"),),
        show_in_player_menu=visible,
    )
    registry = PlayerDetailExtensionRegistry()
    registry.register(action)
    features = FeatureService(
        {conversation: frozenset({"seer_player"})}, {}, frozenset({actor})
    )
    sessions = PortableQuerySessions()
    operation = build_portable_player_operations(
        cast("Any", _PlayerService()),
        _resolver(),
        sessions,
        features,
        registry,
    )["seer.player.query"]
    reply = await operation(context.text, context)
    assert isinstance(reply, PortableReply)
    assert ("【详细资料】" in _text(reply)) is visible
    query.assert_not_awaited()
    other = _context("详细资料", platform=platform)
    other = replace(
        other,
        message=replace(
            other.message, actor=ActorRef(platform, "other"), group_role="owner"
        ),
    )
    rejected = await query_player_extension(action, 700002, other, features, sessions)
    assert not rejected.message.request_succeeded
    query.assert_not_awaited()
    revoked = FeatureService(
        {conversation: frozenset({"seer_player"})}, {}, frozenset()
    )
    rejected = await query_player_extension(action, 700002, context, revoked, sessions)
    assert not rejected.message.request_succeeded
    query.assert_not_awaited()
