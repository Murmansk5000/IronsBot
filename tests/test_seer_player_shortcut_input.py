# SPDX-License-Identifier: GPL-3.0-or-later
from types import SimpleNamespace
from typing import Any, cast

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.plugins.onebot.seer.query.commands.player import (
    PlayerCommandDependencies,
)
from ironsbot.plugins.onebot.seer.query.commands.player_shortcuts import (
    _resolve_player_shortcut_command,
)
from ironsbot.services.identity.player_accounts import (
    PlayerAccount,
    PlayerAccountRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    PlayerShortcutTargetCommand,
    parse_player_shortcut_command,
)
from tests.helpers.onebot_events import group_message_event

PLAYER_ID = 105_023_264
GROUP_ID = 987_654_321


def _dependencies() -> PlayerCommandDependencies:
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
            ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID)): (
                "sample_player",
            ),
        },
    )
    player = SimpleNamespace(
        default_player_id=lambda actor: PLAYER_ID if actor.id == "456" else None
    )
    return PlayerCommandDependencies(
        player=cast("Any", player),
        features=cast("Any", SimpleNamespace()),
        player_id_resolver=PlayerIdResolver(
            lambda reference, conversation: accounts.resolve_player_id(
                reference,
                conversation=conversation,
            ),
            player.default_player_id,
        ),
    )


def test_shortcut_parser_preserves_the_raw_player_reference() -> None:
    assert parse_player_shortcut_command("收集105023264") == (
        PlayerShortcutTargetCommand("collection", "105023264")
    )
    assert parse_player_shortcut_command("巅峰 示例玩家") == (
        PlayerShortcutTargetCommand("peak", "示例玩家")
    )
    assert parse_player_shortcut_command("群星牌") == (
        PlayerShortcutTargetCommand("autocard", None)
    )


def test_shortcut_target_resolution_uses_the_scoped_alias_lookup() -> None:
    resolved = _resolve_player_shortcut_command(
        _dependencies(),
        group_message_event("收集示例玩家", group_id=GROUP_ID),
        PlayerShortcutTargetCommand("collection", "示例玩家"),
    )

    assert resolved.error is None
    assert resolved.command == PlayerShortcutCommand("collection", PLAYER_ID)


def test_shortcut_target_resolution_uses_one_direct_member_mention() -> None:
    resolved = _resolve_player_shortcut_command(
        _dependencies(),
        group_message_event(
            message=Message([MessageSegment.text("巅峰"), MessageSegment.at(456)]),
            group_id=GROUP_ID,
        ),
        PlayerShortcutTargetCommand("peak", None),
    )

    assert resolved.error is None
    assert resolved.command == PlayerShortcutCommand("peak", PLAYER_ID)


def test_shortcut_target_resolution_rejects_mixed_reference_and_mention() -> None:
    resolved = _resolve_player_shortcut_command(
        _dependencies(),
        group_message_event(
            message=Message(
                [MessageSegment.text("群星牌105023264"), MessageSegment.at(456)]
            ),
            group_id=GROUP_ID,
        ),
        PlayerShortcutTargetCommand("autocard", "105023264"),
    )

    assert resolved.command is None
    assert resolved.error == "米米号或玩家别名和 @成员 不能同时使用，请保留其中一种。"
