# SPDX-License-Identifier: GPL-3.0-or-later
from types import SimpleNamespace
from typing import Any, cast

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.plugins.onebot.seer.query.commands import rank_list
from ironsbot.services.identity.player_accounts import (
    PlayerAccount,
    PlayerAccountRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from tests.helpers.onebot_events import group_message_event

PLAYER_ID = 712_345_678
PRIVATE_GROUP_ID = 987_654_321


def _group() -> SimpleNamespace:
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
        private_alias_groups={
            ConversationRef(Platform.ONEBOT, "group", str(PRIVATE_GROUP_ID)): (
                "sample_player",
            ),
        },
    )
    player = SimpleNamespace(
        default_player_id=lambda actor: PLAYER_ID if actor.id == "456" else None
    )
    return SimpleNamespace(
        player_id_resolver=PlayerIdResolver(
            lambda reference, conversation: accounts.resolve_player_id(
                reference,
                conversation=conversation,
            ),
            player.default_player_id,
        ),
        resources=SimpleNamespace(player=player),
    )


def test_rank_player_input_resolves_a_scoped_player_alias() -> None:
    state: dict[str, object] = {}

    assert rank_list._is_rank_player_command(
        cast("Any", _group()),
        group_message_event("成就榜示例玩家", group_id=PRIVATE_GROUP_ID),
        state,
    )

    resolved = state[rank_list.RANK_PLAYER_COMMAND_KEY]
    assert isinstance(resolved, rank_list._ResolvedRankPlayerCommand)
    assert resolved.error is None
    assert resolved.command is not None
    assert (resolved.command.rank_key, resolved.command.player_id) == (
        "成就点数",
        PLAYER_ID,
    )


def test_rank_player_input_resolves_one_direct_member_mention() -> None:
    state: dict[str, object] = {}
    event = group_message_event(
        message=Message([MessageSegment.text("群星牌榜"), MessageSegment.at(456)]),
        group_id=PRIVATE_GROUP_ID,
    )

    assert rank_list._is_rank_player_command(cast("Any", _group()), event, state)

    resolved = state[rank_list.RANK_PLAYER_COMMAND_KEY]
    assert isinstance(resolved, rank_list._ResolvedRankPlayerCommand)
    assert resolved.error is None
    assert resolved.command is not None
    assert (resolved.command.rank_key, resolved.command.player_id) == (
        "群星牌",
        PLAYER_ID,
    )


def test_rank_player_input_rejects_a_mixed_alias_and_member_mention() -> None:
    state: dict[str, object] = {}
    event = group_message_event(
        message=Message(
            [MessageSegment.text("成就榜示例玩家"), MessageSegment.at(456)]
        ),
        group_id=PRIVATE_GROUP_ID,
    )

    assert rank_list._is_rank_player_command(cast("Any", _group()), event, state)

    resolved = state[rank_list.RANK_PLAYER_COMMAND_KEY]
    assert isinstance(resolved, rank_list._ResolvedRankPlayerCommand)
    assert resolved.command is None
    assert resolved.error == "米米号或玩家别名和 @成员 不能同时使用，请保留其中一种。"
