# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.config.player_accounts import PlayerAccount, PlayerAccountRegistry
from ironsbot.plugins.seer.query.commands import team
from ironsbot.plugins.seer.query.commands.player_target import PlayerTargetResolution
from ironsbot.services.seer.team import SeerTeamQueryService
from tests.helpers.onebot_events import group_message_event

PLAYER_ID = 105_023_264
OTHER_PLAYER_ID = 712_345_678
TEAM_ID = 9_447_985


def _binding_for(user_id: int) -> int | None:
    return {123: OTHER_PLAYER_ID, 456: PLAYER_ID}.get(user_id)


def _group() -> Any:
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
                player_id=OTHER_PLAYER_ID,
                name="worker_two",
                aliases=("玩家2",),
                password=None,
                public=True,
            ),
        )
    )
    return SimpleNamespace(
        player_accounts=accounts,
        resources=SimpleNamespace(
            team_query=SimpleNamespace(
                parse_team_ids=SeerTeamQueryService.parse_team_ids,
            ),
            player=SimpleNamespace(default_player_id=_binding_for),
        ),
        features=SimpleNamespace(is_superuser=lambda _user_id: False),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("战队9447985", (TEAM_ID,)),
        ("战队9447985 123456", (TEAM_ID, 123456)),
        ("查询战队信息9447985", (TEAM_ID,)),
    ],
)
def test_team_command_keeps_pure_numbers_as_team_ids(
    text: str,
    expected: tuple[int, ...],
) -> None:
    state: dict[str, object] = {}

    assert team._capture_team_ids(_group(), group_message_event(text), state)
    assert state[team.TEAM_IDS_KEY] == expected
    assert team.PLAYER_TARGET_KEY not in state


@pytest.mark.parametrize(
    ("text", "expected_player_id"),
    [
        ("战队米米号105023264", PLAYER_ID),
        ("战队玩家1", PLAYER_ID),
        ("战队worker_one", PLAYER_ID),
        ("查询战队信息玩家1", PLAYER_ID),
    ],
)
def test_team_command_resolves_explicit_player_targets(
    text: str,
    expected_player_id: int,
) -> None:
    state: dict[str, object] = {}

    assert team._capture_team_ids(_group(), group_message_event(text), state)
    target = state[team.PLAYER_TARGET_KEY]
    assert isinstance(target, PlayerTargetResolution)
    assert target.player_id == expected_player_id
    assert target.is_shortcut_target is not text.startswith("战队米米号")
    assert team.TEAM_IDS_KEY not in state


def test_team_command_keeps_digits_inside_alias_out_of_team_ids() -> None:
    state: dict[str, object] = {}

    assert team._capture_team_ids(_group(), group_message_event("战队玩家1"), state)
    assert team.TEAM_IDS_KEY not in state


def test_team_command_returns_partial_alias_choices() -> None:
    state: dict[str, object] = {}

    assert team._capture_team_ids(_group(), group_message_event("战队玩家"), state)
    target = state[team.PLAYER_TARGET_KEY]
    assert isinstance(target, PlayerTargetResolution)
    assert [choice.label for choice in target.choices] == ["玩家1", "玩家2"]


@pytest.mark.asyncio
async def test_team_handler_uses_the_shared_player_target_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, object] = {}
    event = group_message_event("战队玩家")
    group = _group()
    assert team._capture_team_ids(group, event, state)
    captured: list[PlayerTargetResolution] = []

    async def enter_selection(
        _matcher: object,
        _event: object,
        _state: object,
        target: PlayerTargetResolution,
        _select: object,
    ) -> None:
        captured.append(target)

    monkeypatch.setattr(team, "enter_player_target_selection", enter_selection)

    await team._handle_team_query(
        cast("Any", group),
        cast("Any", object()),
        event,
        state,
    )

    assert len(captured) == 1
    assert [choice.label for choice in captured[0].choices] == ["玩家1", "玩家2"]


def test_team_command_accepts_a_bound_member_target() -> None:
    state: dict[str, object] = {}
    event = group_message_event(
        message=Message([MessageSegment.text("战队"), MessageSegment.at(456)]),
    )

    assert team._capture_team_ids(_group(), event, state)
    target = state[team.PLAYER_TARGET_KEY]
    assert isinstance(target, PlayerTargetResolution)
    assert target.player_id == PLAYER_ID
    assert target.is_shortcut_target


def test_team_command_preserves_member_target_validation() -> None:
    state: dict[str, object] = {}
    event = group_message_event(
        message=Message(
            [
                MessageSegment.text("战队玩家1"),
                MessageSegment.at(456),
            ]
        ),
    )

    assert team._capture_team_ids(_group(), event, state)
    target = state[team.PLAYER_TARGET_KEY]
    assert isinstance(target, PlayerTargetResolution)
    assert target.error == "米米号或玩家别名和 @成员 不能同时使用，请保留其中一种。"


def test_team_command_leaves_unknown_alias_unmatched() -> None:
    state: dict[str, object] = {}

    assert not team._capture_team_ids(
        _group(),
        group_message_event("战队不知道是谁"),
        state,
    )
    target = state[team.PLAYER_TARGET_KEY]
    assert isinstance(target, PlayerTargetResolution)
    assert not target.recognized


@pytest.mark.asyncio
async def test_explicit_player_id_is_not_treated_as_a_protected_shortcut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies: list[str] = []
    queried: list[int] = []

    async def query_player_team(player_id: int, _actor: object) -> str:
        queried.append(player_id)
        return "战队结果"

    async def finish_reply(_matcher: object, _event: object, reply: str) -> None:
        replies.append(reply)

    group = _group()
    group.resources.team_query.query_player_team = query_player_team
    group.resources.player.shortcut_target_access_error = (
        lambda _requester, _player_id: "快捷查询已禁用"
    )
    monkeypatch.setattr(team, "finish_event_reply", finish_reply)

    await team._query_player_team(
        cast("Any", group),
        PlayerTargetResolution(PLAYER_ID, offer_binding=True),
        cast("Any", object()),
        group_message_event("战队米米号105023264"),
    )

    assert queried == [PLAYER_ID]
    assert replies == ["战队结果"]
