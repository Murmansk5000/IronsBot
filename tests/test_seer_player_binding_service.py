import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.commands import parse_confirmation
from ironsbot.integrations.storage.player_bindings import (
    SqlitePlayerBindingStore,
)
from ironsbot.services.seer.player_binding import (
    PlayerBindingState,
    player_binding_offer_message,
    player_binding_replacement_offer_message,
)
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_service import (
    PendingPlayerQuery,
    PlayerQueryResult,
    PlayerService,
)
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


def test_player_binding_offer_only_displays_short_reply_choices() -> None:
    message = player_binding_offer_message(
        _PLAYER_ID,
        "测试玩家",
        unbound_daily_limit=1,
        bound_default_daily_limit=10,
    )

    assert "已查到米米号：123456（测试玩家）" in message
    assert "回复“是”或“y”确认，回复“否”或“n”跳过。" in message
    assert "实时数据的每日额度可从 1 次提升至 10 次" in message
    assert "yes" not in message
    assert "no" not in message
    assert "确认 / 确定" not in message


def test_player_binding_offer_omits_quota_hint_without_an_increase() -> None:
    message = player_binding_offer_message(
        _PLAYER_ID,
        "测试玩家",
        unbound_daily_limit=2,
        bound_default_daily_limit=2,
    )

    assert "实时数据的每日额度可从" not in message


def test_player_binding_replacement_offer_names_both_accounts() -> None:
    message = player_binding_replacement_offer_message(
        10001,
        "旧账号",
        _PLAYER_ID,
        "测试玩家",
    )

    assert "当前默认米米号：10001（旧账号）" in message
    assert "已查到米米号：123456（测试玩家）" in message
    assert "保留当前绑定" in message


class _UnboundPlayerBindingStore:
    def get(self, _qq_user_id: int) -> SimpleNamespace:
        return SimpleNamespace(player_id=None)


def test_shortcut_without_a_default_player_explains_player_id_lookup() -> None:
    service = PlayerService(
        config=cast("Any", None),
        headless=cast("Any", None),
        bindings=cast("Any", _UnboundPlayerBindingStore()),
        error_message=cast("Any", None),
        details=cast("Any", None),
    )

    reply = asyncio.run(
        service.shortcut(
            PlayerShortcutCommand(kind="peak", player_id=None),
            qq_user_id=10001,
        )
    )

    assert reply.text == unbound_player_shortcut_message()


def test_direct_binding_queries_then_saves_and_returns_player_info() -> None:
    pending = PendingPlayerQuery(
        player_id=_PLAYER_ID,
        user_info=SimpleNamespace(nick="测试玩家"),
        more_info=object(),
        player_message="玩家信息",
        section_plan=cast("Any", object()),
    )
    service = object.__new__(PlayerService)
    service._bindings = SimpleNamespace(  # type: ignore[attr-defined]
        get=Mock(return_value=PlayerBindingState(10001))
    )
    service.query = AsyncMock(return_value=PlayerQueryResult(pending=pending))
    service._save_binding = Mock(return_value="已设置默认米米号：123456。")

    result = asyncio.run(
        service.bind_player(
            _PLAYER_ID,
            qq_user_id=10001,
            group_id=20002,
        )
    )

    service.query.assert_awaited_once_with(
        _PLAYER_ID,
        qq_user_id=10001,
        explicit=True,
        group_id=20002,
    )
    service._save_binding.assert_called_once_with(10001, pending)
    assert result.offer_binding is False
    assert result.pending is pending
    assert pending.player_message.startswith("已设置默认米米号：123456。\n\n")


def test_rebinding_the_same_player_skips_query_and_keeps_binding() -> None:
    service = object.__new__(PlayerService)
    service._bindings = SimpleNamespace(  # type: ignore[attr-defined]
        get=Mock(
            return_value=PlayerBindingState(
                10001,
                _PLAYER_ID,
                "测试玩家",
                choice_completed=True,
                last_changed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )
        )
    )
    service.query = AsyncMock()

    result = asyncio.run(service.bind_player(_PLAYER_ID, qq_user_id=10001))

    assert result.message == "当前已绑定该米米号：123456（测试玩家）。"
    service.query.assert_not_awaited()


def test_rebinding_a_different_player_requires_confirmation() -> None:
    pending = PendingPlayerQuery(
        player_id=_PLAYER_ID,
        user_info=SimpleNamespace(nick="测试玩家"),
        more_info=object(),
        player_message="玩家信息",
        section_plan=cast("Any", object()),
    )
    previous = PlayerBindingState(
        10001,
        777777,
        "旧账号",
        choice_completed=True,
    )
    service = object.__new__(PlayerService)
    service._bindings = SimpleNamespace(get=Mock(return_value=previous))  # type: ignore[attr-defined]
    service._binding_change_error = Mock(return_value="")
    service.query = AsyncMock(return_value=PlayerQueryResult(pending=pending))
    service._save_binding = Mock()

    result = asyncio.run(service.bind_player(_PLAYER_ID, qq_user_id=10001))

    assert result.pending is pending
    assert result.offer_binding is True
    assert result.binding_replacement == previous
    service._save_binding.assert_not_called()


def test_declining_a_rebinding_keeps_the_existing_binding() -> None:
    pending = PendingPlayerQuery(
        player_id=_PLAYER_ID,
        user_info=SimpleNamespace(nick="测试玩家"),
        more_info=object(),
        player_message="玩家信息",
        section_plan=cast("Any", object()),
    )
    bindings = SimpleNamespace(decline=Mock())
    service = object.__new__(PlayerService)
    service._bindings = bindings  # type: ignore[attr-defined]

    result = service.save_binding_choice(
        10001,
        pending,
        accepted=False,
        replacing_existing=True,
    )

    assert result == "已保留当前默认米米号。"
    bindings.decline.assert_not_called()


def test_direct_binding_returns_invalid_player_error_without_saving() -> None:
    service = object.__new__(PlayerService)
    service._bindings = SimpleNamespace(  # type: ignore[attr-defined]
        get=Mock(return_value=PlayerBindingState(10001))
    )
    service.query = AsyncMock(
        return_value=PlayerQueryResult(message="❌ 米米号无效，请输入数字。")
    )
    service._save_binding = Mock()

    result = asyncio.run(
        service.bind_player(1, qq_user_id=10001)
    )

    assert result.message == "❌ 米米号无效，请输入数字。"
    service._save_binding.assert_not_called()


def test_all_player_service_entries_reject_invalid_player_id_before_io() -> None:
    service = PlayerService(
        config=cast("Any", None),
        headless=cast("Any", None),
        bindings=cast("Any", None),
        error_message=cast("Any", None),
        details=cast("Any", None),
    )

    async def run() -> None:
        query = await service.query(1, qq_user_id=10001, explicit=True)
        shortcut = await service.shortcut(
            PlayerShortcutCommand(kind="peak", player_id=1),
            qq_user_id=10001,
        )

        assert "50000 ~ 2000000000" in query.message
        assert "50000 ~ 2000000000" in shortcut.text

    asyncio.run(run())


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


def test_binding_change_cooldown_uses_three_beijing_calendar_days(
    tmp_path: Path,
) -> None:
    china_timezone = timezone(timedelta(hours=8))
    changed_at = datetime(2026, 7, 23, 17, 31, tzinfo=china_timezone)
    store = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    store.bind(
        qq_user_id=10003,
        player_id=_PLAYER_ID,
        player_nick="测试玩家",
        changed_at=changed_at,
    )
    config = SimpleNamespace(
        player=SimpleNamespace(
            binding=SimpleNamespace(change_cooldown_days=3),
        )
    )
    service = PlayerService(
        config=cast("Any", config),
        headless=cast("Any", None),
        bindings=store,
        error_message=cast("Any", None),
        details=cast("Any", None),
        now=lambda: datetime(2026, 7, 25, 23, 59, 59, tzinfo=china_timezone),
    )

    assert (
        service.unbind(10003)
        == "默认米米号最近刚更改，请于 2026年07月26日 00:00 起再试。"
    )
    assert store.get(10003).player_id == _PLAYER_ID

    service_after_cooldown = PlayerService(
        config=cast("Any", config),
        headless=cast("Any", None),
        bindings=store,
        error_message=cast("Any", None),
        details=cast("Any", None),
        now=lambda: datetime(2026, 7, 26, 0, 0, tzinfo=china_timezone),
    )
    assert service_after_cooldown.unbind(10003) == "已解除默认米米号。"


def test_rebinding_same_player_does_not_refresh_last_changed_at(tmp_path: Path) -> None:
    store = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    first_changed_at = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    store.bind(
        qq_user_id=10003,
        player_id=_PLAYER_ID,
        player_nick="测试玩家",
        changed_at=first_changed_at,
    )
    store.bind(
        qq_user_id=10003,
        player_id=_PLAYER_ID,
        player_nick="新昵称",
        changed_at=datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
    )

    binding = store.get(10003)
    assert binding.last_changed_at == first_changed_at
    assert binding.player_nick == "测试玩家"
