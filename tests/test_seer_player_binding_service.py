import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ironsbot.core.commands import parse_confirmation
from ironsbot.integrations.storage.player_bindings import (
    SqlitePlayerBindingStore,
)
from ironsbot.services.seer.player_binding import (
    parse_player_binding_target,
    player_binding_offer_message,
)
from ironsbot.services.seer.player_service import PlayerService
from ironsbot.services.seer.player_shortcuts import PlayerShortcutCommand

_PLAYER_ID = 123456


@pytest.mark.parametrize("text", ["是", "yes", "YES", " y ", "确认", "确定"])
def test_parse_confirmation_accepts_yes_replies(text: str) -> None:
    assert parse_confirmation(text) is True


@pytest.mark.parametrize("text", ["否", "no", "NO", " n ", "取消"])
def test_parse_confirmation_accepts_no_replies(text: str) -> None:
    assert parse_confirmation(text) is False


@pytest.mark.parametrize("text", ["", "绑定", "不绑定", "也许", "yes please"])
def test_parse_confirmation_requires_exact_reply(text: str) -> None:
    assert parse_confirmation(text) is None


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


class _UnboundPlayerBindingStore:
    def get(self, _qq_user_id: int) -> SimpleNamespace:
        return SimpleNamespace(player_id=None)


def test_shortcut_without_a_default_player_mentions_direct_binding() -> None:
    service = PlayerService(
        config=cast("Any", None),
        headless=cast("Any", None),
        bindings=cast("Any", _UnboundPlayerBindingStore()),
        error_message=cast("Any", None),
        details=cast("Any", None),
    )

    message = asyncio.run(
        service.shortcut(
            PlayerShortcutCommand(kind="peak", player_id=None),
            qq_user_id=10001,
        )
    )

    assert "绑定米米号12345" in message
    assert "米米号+数字" in message


def test_player_binding_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "bindings.sqlite"
    store = SqlitePlayerBindingStore(path)

    initial = store.get(10001)
    assert initial.player_id is None
    assert initial.choice_completed is False

    store.bind(
        qq_user_id=10001,
        player_id=_PLAYER_ID,
        player_nick="测试玩家",
    )
    bound = store.get(10001)
    assert bound.player_id == _PLAYER_ID
    assert bound.player_nick == "测试玩家"
    assert bound.choice_completed is True

    assert store.unbind(qq_user_id=10001) is True
    unbound = store.get(10001)
    assert unbound.player_id is None
    assert unbound.choice_completed is True
    assert store.unbind(qq_user_id=10001) is False


def test_declining_binding_completes_first_choice(tmp_path: Path) -> None:
    path = tmp_path / "bindings.sqlite"
    store = SqlitePlayerBindingStore(path)
    store.decline(qq_user_id=10002)

    state = store.get(10002)
    assert state.player_id is None
    assert state.choice_completed is True
