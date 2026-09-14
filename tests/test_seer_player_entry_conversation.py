from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.plugins.onebot.seer.query.commands import player, player_shortcuts
from ironsbot.services.identity.player_accounts import (
    PlayerAccount,
    PlayerAccountRegistry,
)
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_result import QueryReply
from tests.helpers.onebot_events import group_message_event

PLAYER_ID = 949_105_380


def _resolver() -> PlayerIdResolver:
    accounts = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=PLAYER_ID,
                name="sample_player",
                aliases=("示例账号",),
                password=None,
                public=True,
            ),
        )
    )
    return PlayerIdResolver(
        lambda reference, conversation: accounts.resolve_player_id(
            reference,
            conversation=conversation,
        ),
        lambda _actor: None,
    )


def _dependencies(
    extensions: PlayerDetailExtensionRegistry | None = None,
) -> player.PlayerCommandDependencies:
    return player.PlayerCommandDependencies(
        cast("Any", SimpleNamespace()),
        cast("Any", SimpleNamespace()),
        detail_extensions=extensions or PlayerDetailExtensionRegistry(),
        player_id_resolver=_resolver(),
    )


def test_player_query_matcher_accepts_known_targets_only() -> None:
    dependencies = _dependencies()

    assert asyncio.run(
        player._is_player_id_query(
            dependencies,
            group_message_event(f"米米号{PLAYER_ID}"),
            {},
        )
    )
    assert asyncio.run(
        player._is_player_id_query(
            dependencies,
            group_message_event("米米号示例账号"),
            {},
        )
    )
    assert not asyncio.run(
        player._is_player_id_query(
            dependencies,
            group_message_event("米米号是什么"),
            {},
        )
    )


def test_binding_matcher_leaves_resolution_to_portable_operation() -> None:
    assert asyncio.run(
        player._is_binding_command(
            group_message_event("绑定米米号示例账号"),
            {},
        )
    )


def test_extension_shortcut_onebot_rule_delegates_to_portable_resolution() -> None:
    extensions = PlayerDetailExtensionRegistry()
    action = PlayerDetailExtensionAction(
        id="private_lineup",
        feature="player_lineup_private",
        label="阵容",
        aliases=("阵容",),
        command_help_id="private_player_lineup.query",
        query=AsyncMock(return_value=QueryReply(text="ok")),
        action=ActionDefinition("private_lineup", "阵容"),
    )
    extensions.register(action)
    dependencies = _dependencies(extensions)

    assert asyncio.run(
        player_shortcuts._is_player_extension_shortcut(
            group_message_event("阵容示例账号"),
            dependencies=dependencies,
            action=action,
        )
    )


def test_player_alias_resolution_remains_conversation_scoped() -> None:
    resolver = _resolver()
    conversation = ConversationRef(Platform.ONEBOT, "group", "123")

    assert resolver.has_known_reference(
        "示例账号",
        ActorRef(Platform.ONEBOT, "456"),
        conversation,
    )
