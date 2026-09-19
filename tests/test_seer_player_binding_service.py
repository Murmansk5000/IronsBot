import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.seer import SeerConfig
from ironsbot.core.commands import parse_confirmation
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.player_bindings import (
    SqlitePlayerBindingStore,
)
from ironsbot.services.seer.player_binding import PlayerBindingState
from ironsbot.services.seer.player_service import (
    PendingPlayerQuery,
    PlayerQueryResult,
    PlayerService,
)
from ironsbot.services.seer.player_shortcut_contracts import PlayerShortcutCommand

_PLAYER_ID = 123456


def _actor(user_id: int = 10001) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


@pytest.mark.parametrize("text", ["是", "yes", "YES", " y ", "确认", "确定"])
def test_parse_confirmation_accepts_yes_replies(text: str) -> None:
    assert parse_confirmation(text) is True


@pytest.mark.parametrize("text", ["否", "no", "NO", " n ", "取消"])
def test_parse_confirmation_accepts_no_replies(text: str) -> None:
    assert parse_confirmation(text) is False


@pytest.mark.parametrize("text", ["", "绑定", "不绑定", "也许", "yes please"])
def test_parse_confirmation_requires_exact_reply(text: str) -> None:
    assert parse_confirmation(text) is None


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
        get=Mock(return_value=PlayerBindingState(_actor()))
    )
    service.query = AsyncMock(return_value=PlayerQueryResult(pending=pending))
    service._save_binding = Mock(return_value="已设置默认米米号：123456。")

    result = asyncio.run(
        service.bind_player(
            _PLAYER_ID,
            actor=_actor(),
            conversation=ConversationRef(Platform.ONEBOT, "group", "20002"),
        )
    )

    service.query.assert_awaited_once_with(
        _PLAYER_ID,
        actor=_actor(),
        explicit=True,
        conversation=ConversationRef(Platform.ONEBOT, "group", "20002"),
    )
    service._save_binding.assert_called_once_with(_actor(), pending)
    assert result.offer_binding is False
    assert result.pending is pending
    assert pending.player_message.startswith("已设置默认米米号：123456。\n\n")


@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
def test_admin_binding_updates_only_target_and_bypasses_its_cooldown(
    tmp_path: Path,
    platform: Platform,
) -> None:
    operator = ActorRef(platform, "operator")
    target = ActorRef(platform, "recipient")
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    store = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    store.bind(actor=target, player_id=777777, player_nick="old", changed_at=now)
    pending = PendingPlayerQuery(
        player_id=_PLAYER_ID,
        user_info=SimpleNamespace(nick="new"),
        more_info=object(),
        player_message="player information",
        section_plan=cast("Any", object()),
    )
    service = PlayerService(
        config=SeerConfig(),
        headless=cast("Any", None),
        bindings=store,
        error_message=cast("Any", None),
        details=cast("Any", None),
        now=lambda: now,
    )
    service.query = AsyncMock(return_value=PlayerQueryResult(pending=pending))
    result = asyncio.run(service.bind_player(_PLAYER_ID, actor=operator, target=target))
    assert store.get(target).player_id == _PLAYER_ID
    assert store.get(operator).player_id is None
    assert result.binding_replacement is None
    assert result.offer_binding is False
    assert pending.player_message.startswith("已为该成员设置默认米米号")
    service.query.assert_awaited_once_with(
        _PLAYER_ID,
        actor=operator,
        explicit=True,
        conversation=None,
    )


def test_rebinding_the_same_player_skips_query_and_keeps_binding() -> None:
    service = object.__new__(PlayerService)
    service._bindings = SimpleNamespace(  # type: ignore[attr-defined]
        get=Mock(
            return_value=PlayerBindingState(
                _actor(),
                _PLAYER_ID,
                "测试玩家",
                choice_completed=True,
                last_changed_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )
        )
    )
    service.query = AsyncMock()

    result = asyncio.run(service.bind_player(_PLAYER_ID, actor=_actor()))

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
        _actor(),
        777777,
        "旧账号",
        choice_completed=True,
    )
    service = object.__new__(PlayerService)
    service._bindings = SimpleNamespace(get=Mock(return_value=previous))  # type: ignore[attr-defined]
    service._binding_change_error = Mock(return_value="")
    service.query = AsyncMock(return_value=PlayerQueryResult(pending=pending))
    service._save_binding = Mock()

    result = asyncio.run(service.bind_player(_PLAYER_ID, actor=_actor()))

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
        _actor(),
        pending,
        accepted=False,
        replacing_existing=True,
    )

    assert result == "已保留当前默认米米号。"
    bindings.decline.assert_not_called()


def test_direct_binding_returns_invalid_player_error_without_saving() -> None:
    service = object.__new__(PlayerService)
    service._bindings = SimpleNamespace(  # type: ignore[attr-defined]
        get=Mock(return_value=PlayerBindingState(_actor()))
    )
    service.query = AsyncMock(
        return_value=PlayerQueryResult(message="❌ 米米号无效，请输入数字。")
    )
    service._save_binding = Mock()

    result = asyncio.run(service.bind_player(1, actor=_actor()))

    assert result.message == "❌ 米米号无效，请输入数字。"
    service._save_binding.assert_not_called()


def test_all_player_service_entries_reject_invalid_player_id_before_io() -> None:
    service = PlayerService(
        config=SeerConfig(),
        headless=cast("Any", None),
        bindings=cast("Any", None),
        error_message=cast("Any", None),
        details=cast("Any", None),
    )

    async def run() -> None:
        query = await service.query(1, actor=_actor(), explicit=True)
        shortcut = await service.shortcut(
            PlayerShortcutCommand(kind="peak", player_id=1),
            actor=_actor(),
        )

        assert "50000 ~ 2000000000" in query.message
        assert "50000 ~ 2000000000" in shortcut.text

    asyncio.run(run())


def test_player_binding_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "bindings.sqlite"
    store = SqlitePlayerBindingStore(path)

    initial = store.get(_actor())
    assert initial.player_id is None
    assert initial.choice_completed is False

    store.bind(
        actor=_actor(),
        player_id=_PLAYER_ID,
        player_nick="测试玩家",
    )
    bound = store.get(_actor())
    assert bound.player_id == _PLAYER_ID
    assert bound.player_nick == "测试玩家"
    assert bound.choice_completed is True

    assert store.unbind(actor=_actor()) is True
    unbound = store.get(_actor())
    assert unbound.player_id is None
    assert unbound.choice_completed is True
    assert store.unbind(actor=_actor()) is False


def test_player_binding_store_keeps_platform_and_member_scope_isolated(
    tmp_path: Path,
) -> None:
    store = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    actors = (
        ActorRef(Platform.ONEBOT, "10001"),
        ActorRef(Platform.QQ_OFFICIAL, "10001"),
        ActorRef(
            Platform.QQ_OFFICIAL,
            "10001",
            kind="member",
            scope_id="guild-a",
        ),
        ActorRef(
            Platform.QQ_OFFICIAL,
            "10001",
            kind="member",
            scope_id="guild-b",
        ),
    )

    for player_id, actor in enumerate(actors, start=1):
        store.bind(
            actor=actor,
            player_id=player_id,
            player_nick=f"player-{player_id}",
        )

    assert [store.get(actor).player_id for actor in actors] == [1, 2, 3, 4]


def test_declining_binding_completes_first_choice(tmp_path: Path) -> None:
    path = tmp_path / "bindings.sqlite"
    store = SqlitePlayerBindingStore(path)
    store.decline(actor=_actor(10002))

    state = store.get(_actor(10002))
    assert state.player_id is None
    assert state.choice_completed is True


def test_binding_change_cooldown_uses_three_beijing_calendar_days(
    tmp_path: Path,
) -> None:
    china_timezone = timezone(timedelta(hours=8))
    changed_at = datetime(2026, 7, 23, 17, 31, tzinfo=china_timezone)
    store = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    store.bind(
        actor=_actor(10003),
        player_id=_PLAYER_ID,
        player_nick="测试玩家",
        changed_at=changed_at,
    )
    config = SeerConfig()
    service = PlayerService(
        config=cast("Any", config),
        headless=cast("Any", None),
        bindings=store,
        error_message=cast("Any", None),
        details=cast("Any", None),
        now=lambda: datetime(2026, 7, 25, 23, 59, 59, tzinfo=china_timezone),
    )

    assert (
        service.unbind(_actor(10003))
        == "默认米米号最近刚更改，请于 2026年07月26日 00:00 起再试。"
    )
    assert store.get(_actor(10003)).player_id == _PLAYER_ID

    service_after_cooldown = PlayerService(
        config=cast("Any", config),
        headless=cast("Any", None),
        bindings=store,
        error_message=cast("Any", None),
        details=cast("Any", None),
        now=lambda: datetime(2026, 7, 26, 0, 0, tzinfo=china_timezone),
    )
    assert service_after_cooldown.unbind(_actor(10003)) == "已解除默认米米号。"


def test_rebinding_same_player_does_not_refresh_last_changed_at(tmp_path: Path) -> None:
    store = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    first_changed_at = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    store.bind(
        actor=_actor(10003),
        player_id=_PLAYER_ID,
        player_nick="测试玩家",
        changed_at=first_changed_at,
    )
    store.bind(
        actor=_actor(10003),
        player_id=_PLAYER_ID,
        player_nick="新昵称",
        changed_at=datetime(2026, 8, 3, 12, tzinfo=timezone.utc),
    )

    binding = store.get(_actor(10003))
    assert binding.last_changed_at == first_changed_at
    assert binding.player_nick == "测试玩家"
