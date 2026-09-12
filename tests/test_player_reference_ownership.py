from __future__ import annotations

import asyncio
from functools import partial
from unittest.mock import Mock

import pytest

from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.player_reference_commands import player_reference_input_matcher
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.onebot.context import command_context
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.plugins.onebot.ai import _capture_ai_prompt
from ironsbot.plugins.onebot.seer.query.commands.player import _is_binding_command
from ironsbot.services.identity.player_accounts import (
    PlayerAccount,
    PlayerAccountRegistry,
)
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.player_query import extract_player_query_arg
from tests.helpers.onebot_events import group_message_event, private_message_event

_ADMIN = ActorRef(Platform.ONEBOT, "100")
_REGULAR = ActorRef(Platform.ONEBOT, "200")
_GROUP = ConversationRef(Platform.ONEBOT, "group", "300")
_PLAYER_ID = 123456


@pytest.mark.parametrize(
    "prefix", ("米米号", "查询玩家信息", "收集", "巅峰", "群星牌", "绑定米米号")
)
@pytest.mark.parametrize(
    ("actor", "group", "reference", "expected"),
    (
        (_ADMIN, False, "私有示例", True),
        (_REGULAR, False, "私有示例", False),
        (_REGULAR, True, "私有示例", True),
        (_REGULAR, False, "公开示例", True),
        (_ADMIN, False, "不认识的玩家", False),
        (_ADMIN, False, "123456", True),
    ),
)
def test_player_command_ownership_matches_resolution(
    *, prefix: str, actor: ActorRef, group: bool, reference: str, expected: bool
) -> None:
    registry = PlayerAccountRegistry(
        (
            PlayerAccount(_PLAYER_ID, "私有示例", (), None),
            PlayerAccount(_PLAYER_ID + 1, "公开示例", (), None, public=True),
        ),
        private_alias_groups={_GROUP: ("私有示例",)},
    )
    features = FeatureService(
        group_features={_GROUP: frozenset({"seer_player", "ai_chat"})},
        actor_features={_REGULAR: frozenset({"seer_player", "ai_chat"})},
        superusers=frozenset({_ADMIN}),
    )
    binding = Mock(side_effect=AssertionError("ownership must not load bindings"))
    resolver = PlayerIdResolver(
        lambda reference, conversation: registry.resolve_player_id(
            reference, conversation=conversation
        ),
        binding,
        privileged_reference_lookup=lambda reference, conversation: (
            registry.resolve_player_id(
                reference, conversation=conversation, include_private=True
            )
        ),
        is_privileged_actor=features.is_actor_superuser,
    )
    commands = tuple(
        command
        for command in seer_command_contracts(resolver)
        if command.id.startswith("seer.player.")
    )
    catalog = CommandCatalog()
    catalog.load(
        (PluginContribution(id="seer_query", commands=commands),),
        known_features={"seer_player"},
    )
    event_factory = (
        partial(group_message_event, group_id=int(_GROUP.id))
        if group
        else private_message_event
    )
    text = prefix + reference
    event = event_factory(text, user_id=int(actor.id))

    target = resolver.resolve(message_input_context(event), reference)
    assert (target.player_id is not None) is expected
    assert (
        catalog.claims_direct_input(command_context(event), features, text) is expected
    )
    if not group:
        # Exercise the actual AI routing rule, without invoking a completion API.
        assert _capture_ai_prompt(event, {}, features, catalog) is not expected
    binding.assert_not_called()


@pytest.mark.parametrize("prefix", ["米米号", "绑定米米号"])
@pytest.mark.parametrize("split_at", [1, 2])
def test_player_ownership_preserves_literal_command_prefix(
    prefix: str, split_at: int,
) -> None:
    text = prefix[:split_at] + " " + prefix[split_at:] + "123456"
    event = private_message_event(text)
    context = command_context(event)
    matcher = player_reference_input_matcher((prefix,), lambda *_: False)
    actual = (
        asyncio.run(_is_binding_command(event, {}))
        if prefix == "绑定米米号"
        else extract_player_query_arg(text) is not None
    )
    assert not actual
    assert matcher(text, context) is actual
