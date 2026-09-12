from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, cast
from unittest.mock import Mock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.player_reference_commands import player_reference_input_matcher
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.onebot.context import command_context
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.plugins.onebot.ai import _capture_ai_prompt
from ironsbot.plugins.onebot.seer.query.commands import (
    player,
    player_shortcuts,
    rank_list,
)
from ironsbot.plugins.onebot.seer.query.commands.player import _is_binding_command
from ironsbot.plugins.onebot.seer.query.group import SeerMatcherGroup
from ironsbot.services.identity.player_accounts import (
    PlayerAccount,
    PlayerAccountRegistry,
)
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
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
    prefix: str,
    split_at: int,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prefix,index",
    [
        ("绑定米米号", 0),
        ("米米号", 1),
        ("收集", 0),
        ("巅峰", 0),
        ("群星牌", 0),
        ("成就榜", 1),
    ],
)
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "target",
    ["numeric", "alias", "member", "bot", "mixed", "multiple", "unbound", "reply"],
)
async def test_installed_player_rules_admit_member_targets_and_enforce_feature(
    prefix: str,
    index: int,
    target: str,
    *,
    enabled: bool,
) -> None:
    features = FeatureService(
        {_GROUP: frozenset({"seer_player", "seer_rank"})} if enabled else {},
        {},
        frozenset(),
    )
    resolver = PlayerIdResolver(
        lambda reference, _conversation: (
            _PLAYER_ID if reference in {str(_PLAYER_ID), "示例玩家"} else None
        ),
        lambda actor: _PLAYER_ID if actor.id == "456" else None,
    )
    group = Mock(spec=SeerMatcherGroup)
    group.features = features
    group.player_id_resolver = resolver
    group.resources = Mock()
    group.resources.player_detail_extensions = PlayerDetailExtensionRegistry()
    if prefix == "成就榜":
        rank_list.install(group)
    elif prefix in {"收集", "巅峰", "群星牌"}:
        player_shortcuts.install(group)
    else:
        player.install(group)
    message = Message(prefix)
    if target in {"numeric", "alias"}:
        message += str(_PLAYER_ID) if target == "numeric" else "示例玩家"
    else:
        message += MessageSegment.at(
            1 if target == "bot" else 789 if target == "unbound" else 456
        )
        if target == "mixed":
            message += "示例玩家"
        elif target == "multiple":
            message += MessageSegment.at(789)
    event = group_message_event(
        message=message,
        group_id=int(_GROUP.id),
        reply_sender_user_id=456 if target == "reply" else None,
    )
    if event.reply is not None:
        event.reply.message = Message([MessageSegment.at(789)])
    rule = group.on_message.call_args_list[index].kwargs["rule"]
    state: dict[str, Any] = {}
    admitted = enabled and target != "bot"
    assert await rule(cast("Any", None), event, state) is admitted
    if not admitted or prefix == "绑定米米号":
        return
    if prefix == "米米号":
        resolved = state[player.PLAYER_TARGET_RESOLUTION_KEY]
        player_id = resolved.player_id
    else:
        key = (
            rank_list.RANK_PLAYER_COMMAND_KEY
            if prefix == "成就榜"
            else player_shortcuts._SHORTCUT_COMMAND_KEY
        )
        resolved = state[key]
        player_id = resolved.command.player_id if resolved.command is not None else None
    if target in {"mixed", "multiple", "unbound"}:
        assert player_id is None
        assert resolved.error
    else:
        assert player_id == _PLAYER_ID
        assert resolved.error is None
