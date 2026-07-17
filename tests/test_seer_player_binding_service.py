from pathlib import Path

import pytest

from ironsbot.services.seer.player_binding import (
    bind_player,
    decline_player_binding,
    get_player_binding,
    parse_binding_choice,
    parse_player_binding_target,
    player_binding_offer_message,
    unbind_player,
)

_PLAYER_ID = 123456


@pytest.mark.parametrize("text", ["是", "yes", "YES", " y ", "确认", "确定"])
def test_parse_binding_choice_accepts_yes_replies(text: str) -> None:
    assert parse_binding_choice(text) is True


@pytest.mark.parametrize("text", ["否", "no", "NO", " n ", "取消"])
def test_parse_binding_choice_accepts_no_replies(text: str) -> None:
    assert parse_binding_choice(text) is False


@pytest.mark.parametrize("text", ["", "绑定", "不绑定", "也许", "yes please"])
def test_parse_binding_choice_requires_exact_reply(text: str) -> None:
    assert parse_binding_choice(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("绑定米米号123456", 123456),
        (" 更改米米号123456 ", 123456),
        ("米米号123456", None),
        ("绑定米米号", None),
    ],
)
def test_parse_player_binding_target(text: str, expected: int | None) -> None:
    assert parse_player_binding_target(text) == expected


def test_player_binding_offer_only_displays_short_reply_choices() -> None:
    message = player_binding_offer_message(_PLAYER_ID, "测试玩家")

    assert "已查到米米号：123456（测试玩家）" in message
    assert "回复“是”或“y”确认，回复“否”或“n”跳过。" in message
    assert "yes" not in message
    assert "no" not in message
    assert "确认 / 确定" not in message


def test_player_binding_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "bindings.sqlite"

    initial = get_player_binding(path, 10001)
    assert initial.player_id is None
    assert initial.choice_completed is False

    bind_player(
        path,
        qq_user_id=10001,
        player_id=_PLAYER_ID,
        player_nick="测试玩家",
    )
    bound = get_player_binding(path, 10001)
    assert bound.player_id == _PLAYER_ID
    assert bound.player_nick == "测试玩家"
    assert bound.choice_completed is True

    assert unbind_player(path, qq_user_id=10001) is True
    unbound = get_player_binding(path, 10001)
    assert unbound.player_id is None
    assert unbound.choice_completed is True
    assert unbind_player(path, qq_user_id=10001) is False


def test_declining_binding_completes_first_choice(tmp_path: Path) -> None:
    path = tmp_path / "bindings.sqlite"
    decline_player_binding(path, qq_user_id=10002)

    state = get_player_binding(path, 10002)
    assert state.player_id is None
    assert state.choice_completed is True
