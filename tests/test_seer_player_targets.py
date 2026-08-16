# SPDX-License-Identifier: GPL-3.0-or-later

from types import SimpleNamespace
from typing import Any, cast

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.config.player_accounts import PlayerAccount, PlayerAccountRegistry
from ironsbot.plugins.seer.query.commands import rank_list
from ironsbot.plugins.seer.query.commands.player_target import (
    resolve_event_player_reference,
    resolve_event_player_target,
    resolve_player_target,
)
from ironsbot.plugins.seer.query.commands.rank_list_context import (
    RANK_PLAYER_COMMAND_KEY,
)
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from tests.helpers.onebot_events import group_message_event

PLAYER_ID = 105_023_264
REQUESTER_PLAYER_ID = 712_345_678
UNBOUND_USER_ID = 789


def _binding_for(user_id: int) -> int | None:
    return {123: REQUESTER_PLAYER_ID, 456: PLAYER_ID}.get(user_id)


def test_player_target_uses_one_current_message_member_mention() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("收集"), MessageSegment.at(456)])
    )

    target = resolve_player_target(
        event,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )

    assert target.player_id == PLAYER_ID
    assert not target.offer_binding
    assert target.error is None


def test_player_target_uses_member_mention_sent_after_a_quote() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("收集"), MessageSegment.at(456)]),
        reply_sender_user_id=789,
    )

    target = resolve_player_target(
        event,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )

    assert target.player_id == PLAYER_ID
    assert not target.offer_binding
    assert target.error is None


def test_player_target_member_lookup_does_not_offer_to_bind_another_person() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("群星牌"), MessageSegment.at(456)])
    )

    target = resolve_player_target(
        event,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )

    assert not target.offer_binding


def test_player_target_rejects_ambiguous_member_target_forms() -> None:
    two_members = group_message_event(
        message=Message(
            [
                MessageSegment.text("巅峰"),
                MessageSegment.at(456),
                MessageSegment.at(789),
            ]
        )
    )
    member_and_number = group_message_event(
        message=Message([MessageSegment.text("收集712345678"), MessageSegment.at(456)])
    )

    multiple = resolve_player_target(
        two_members,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )
    mixed = resolve_player_target(
        member_and_number,
        numeric_player_id=105_023_264,
        binding_for_user=_binding_for,
    )

    assert multiple.error == "请一次只 @ 一名成员查询其已绑定的米米号。"
    assert mixed.error == "米米号或玩家别名和 @成员 不能同时使用，请保留其中一种。"


def test_player_target_reports_an_unbound_mentioned_member() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("米米号"), MessageSegment.at(789)])
    )

    target = resolve_player_target(
        event,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )

    assert target.player_id is None
    assert target.error == "该成员尚未绑定米米号。"


def test_unbound_requester_cannot_query_a_member_target() -> None:
    event = group_message_event(
        message=Message([MessageSegment.text("群星牌"), MessageSegment.at(456)]),
        user_id=UNBOUND_USER_ID,
    )

    target = resolve_player_target(
        event,
        numeric_player_id=None,
        binding_for_user=_binding_for,
    )

    assert target.player_id is None
    assert not target.offer_binding
    assert target.error == unbound_player_shortcut_message()


def test_event_player_reference_respects_public_and_group_scoped_aliases() -> None:
    private_group_id = 987654321
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
        private_alias_groups={private_group_id: ("sample_player",)},
    )

    assert (
        resolve_event_player_reference(
            accounts,
            group_message_event("", group_id=private_group_id),
            "示例玩家",
        )
        == PLAYER_ID
    )
    assert (
        resolve_event_player_reference(
            accounts,
            group_message_event("", group_id=123456789),
            "示例玩家",
        )
        is None
    )
    assert (
        resolve_event_player_reference(
            accounts,
            group_message_event(""),
            str(PLAYER_ID),
        )
        == PLAYER_ID
    )


def test_event_player_target_unifies_default_number_alias_and_member_forms() -> None:
    accounts = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=PLAYER_ID,
                name="sample_player",
                aliases=("示例玩家",),
                password=None,
                public=True,
            ),
        )
    )

    default_target = resolve_event_player_target(
        accounts,
        group_message_event("收集"),
        None,
        binding_for_user=_binding_for,
    )
    numeric_target = resolve_event_player_target(
        accounts,
        group_message_event("收集105023264"),
        "105023264",
        binding_for_user=_binding_for,
    )
    alias_target = resolve_event_player_target(
        accounts,
        group_message_event("收集示例玩家"),
        "示例玩家",
        binding_for_user=_binding_for,
    )
    member_target = resolve_event_player_target(
        accounts,
        group_message_event(
            message=Message([MessageSegment.text("收集"), MessageSegment.at(456)])
        ),
        None,
        binding_for_user=_binding_for,
    )

    assert default_target.player_id == REQUESTER_PLAYER_ID
    assert numeric_target.player_id == PLAYER_ID
    assert alias_target.player_id == PLAYER_ID
    assert member_target.player_id == PLAYER_ID


def test_event_player_target_leaves_unknown_aliases_for_other_routes() -> None:
    target = resolve_event_player_target(
        PlayerAccountRegistry(()),
        group_message_event("米米号不知道是谁"),
        "不知道是谁",
        binding_for_user=_binding_for,
    )

    assert not target.recognized
    assert target.error is None


def test_event_player_target_returns_visible_partial_alias_choices() -> None:
    accounts = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=PLAYER_ID,
                name="worker_one",
                aliases=("玩家1",),
                password=None,
                public=True,
            ),
            PlayerAccount(
                player_id=REQUESTER_PLAYER_ID,
                name="worker_two",
                aliases=("玩家2",),
                password=None,
                public=True,
            ),
        )
    )

    target = resolve_event_player_target(
        accounts,
        group_message_event("米米号玩家"),
        "玩家",
        binding_for_user=_binding_for,
        allow_partial_reference=True,
    )

    assert target.recognized
    assert target.player_id is None
    assert [(choice.player_id, choice.label) for choice in target.choices] == [
        (PLAYER_ID, "玩家1"),
        (REQUESTER_PLAYER_ID, "玩家2"),
    ]


def test_event_player_target_resolves_one_visible_partial_alias() -> None:
    accounts = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=PLAYER_ID,
                name="worker_one",
                aliases=("玩家1",),
                password=None,
                public=True,
            ),
        )
    )

    target = resolve_event_player_target(
        accounts,
        group_message_event("米米号玩家"),
        "玩家",
        binding_for_user=_binding_for,
        allow_partial_reference=True,
    )

    assert target.player_id == PLAYER_ID
    assert target.choices == ()


def test_rank_player_target_accepts_a_current_message_member_mention() -> None:
    group = SimpleNamespace(
        player_accounts=PlayerAccountRegistry(()),
        resources=SimpleNamespace(
            player=SimpleNamespace(default_player_id=_binding_for)
        ),
        features=SimpleNamespace(is_superuser=lambda _user_id: False),
    )
    event = group_message_event(
        message=Message([MessageSegment.text("专家榜"), MessageSegment.at(456)])
    )
    state: dict[str, object] = {}

    assert rank_list._is_rank_player_command(cast("Any", group), event, state)
    command = state[RANK_PLAYER_COMMAND_KEY]
    assert isinstance(command, rank_list.RankPlayerTargetCommand)
    assert command.rank_key == "专家段位"
    assert command.target.player_id == PLAYER_ID
