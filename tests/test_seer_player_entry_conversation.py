import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from ironsbot.plugins.seer.query.commands import player, player_shortcuts
from ironsbot.plugins.seer.query.commands.player_context import (
    PLAYER_BINDING_NAMESPACE,
    PLAYER_DETAIL_NAMESPACE,
    PLAYER_UNBOUND_ENTRY_NAMESPACE,
)
from ironsbot.services.seer.player_service import PendingPlayerQuery
from ironsbot.services.seer.player_shortcuts import PlayerShortcutCommand
from tests.helpers.onebot_events import group_message_event


def test_unbound_player_entry_only_accepts_bare_numeric_ids() -> None:
    assert player._is_unbound_player_id_reply(group_message_event("949105380"))
    assert player._is_unbound_player_id_reply(group_message_event(" 949105380 "))
    assert not player._is_unbound_player_id_reply(
        group_message_event("米米号949105380")
    )
    assert not player._is_unbound_player_id_reply(group_message_event("949105380a"))


def test_player_conversation_flows_share_one_session() -> None:
    assert {
        PLAYER_BINDING_NAMESPACE,
        PLAYER_DETAIL_NAMESPACE,
        PLAYER_UNBOUND_ENTRY_NAMESPACE,
    } == {PLAYER_DETAIL_NAMESPACE}


def test_pending_binding_choice_accepts_only_confirmation_replies() -> None:
    assert player._parse_pending_binding_choice("是", 949105380) is True
    assert player._parse_pending_binding_choice("n", 949105380) is False
    assert (
        player._parse_pending_binding_choice("绑定米米号949105380", 949105380)
        is None
    )
    assert (
        player._parse_pending_binding_choice("更改米米号949105380", 949105380)
        is None
    )
    assert (
        player._parse_pending_binding_choice("绑定米米号123456", 949105380)
        is None
    )


def test_pending_confirmation_reuses_the_fetched_player(
    monkeypatch: Any,
) -> None:
    pending = PendingPlayerQuery(
        player_id=949105380,
        user_info=SimpleNamespace(nick="测试玩家"),
        more_info=object(),
        player_message="玩家详情",
        section_plan=cast("Any", object()),
    )
    service = SimpleNamespace(save_binding_choice=Mock())
    send_pending = AsyncMock()
    monkeypatch.setattr(player, "_send_pending_player_query", send_pending)
    event = group_message_event("是")
    matcher = cast("Any", object())
    state: dict[str, object] = {
        player.PLAYER_BINDING_PENDING_KEY: pending,
    }
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )

    asyncio.run(
        player.handle_player_binding_choice(
            dependencies,
            matcher,
            event,
            cast("Any", state),
        )
    )

    service.save_binding_choice.assert_called_once_with(
        event.user_id,
        pending,
        accepted=True,
    )
    send_pending.assert_awaited_once_with(
        dependencies,
        matcher,
        event,
        state,
        pending,
    )


def test_unbound_player_entry_prompt_explains_bare_id_input() -> None:
    prompt = player._unbound_player_entry_prompt("❌ 米米号 949105380 查询失败：不存在")

    assert "请直接发送数字" in prompt
    assert "绑定米米号123456" not in prompt
    assert "949105380 查询失败" in prompt
    assert "查询成功后可按提示选择设为默认" in prompt


def test_unbound_player_entry_reprompts_after_failed_lookup(
    monkeypatch: Any,
) -> None:
    service = SimpleNamespace(
        query=AsyncMock(
            return_value=SimpleNamespace(
                message="❌ 米米号 949105380 查询失败：不存在",
                pending=None,
            )
        )
    )
    prompt = AsyncMock()
    monkeypatch.setattr(player, "prompt_for_unbound_player_id", prompt)
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )

    asyncio.run(
        player.handle_unbound_player_id_entry(
            dependencies,
            cast("Any", object()),
            group_message_event("949105380"),
            {},
        )
    )

    service.query.assert_awaited_once_with(
        949105380,
        qq_user_id=123,
        explicit=True,
        group_id=456,
    )
    assert prompt.await_args is not None
    assert prompt.await_args.kwargs["error"] == "❌ 米米号 949105380 查询失败：不存在"


def test_unbound_player_entry_uses_normal_success_flow(
    monkeypatch: Any,
) -> None:
    result = SimpleNamespace(message="", pending=object(), offer_binding=True)
    service = SimpleNamespace(query=AsyncMock(return_value=result))
    handle_result = AsyncMock()
    monkeypatch.setattr(player, "_handle_player_query_result", handle_result)
    event = group_message_event("949105380")
    state: dict[str, object] = {}
    matcher = cast("Any", object())
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )

    asyncio.run(
        player.handle_unbound_player_id_entry(
            dependencies,
            matcher,
            event,
            state,
        )
    )

    service.query.assert_awaited_once_with(
        949105380,
        qq_user_id=event.user_id,
        explicit=True,
        group_id=event.group_id,
    )
    handle_result.assert_awaited_once_with(
        dependencies,
        matcher,
        event,
        state,
        result,
    )


def test_unbound_player_entry_rejects_short_number_without_query(
    monkeypatch: Any,
) -> None:
    service = SimpleNamespace(query=AsyncMock())
    prompt = AsyncMock()
    monkeypatch.setattr(player, "prompt_for_unbound_player_id", prompt)
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )
    event = group_message_event("1")

    asyncio.run(
        player.handle_unbound_player_id_entry(
            dependencies,
            cast("Any", object()),
            event,
            {},
        )
    )

    service.query.assert_not_awaited()
    assert prompt.await_args is not None
    assert "50000 ~ 2000000000" in prompt.await_args.kwargs["error"]


def test_shortcut_without_default_opens_player_id_entry(
    monkeypatch: Any,
) -> None:
    service = SimpleNamespace(
        default_player_id=lambda _user_id: None,
        shortcut=AsyncMock(),
    )
    prompt = AsyncMock()
    monkeypatch.setattr(player_shortcuts, "prompt_for_unbound_player_id", prompt)
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )
    state: dict[str, object] = {
        player_shortcuts._SHORTCUT_COMMAND_KEY: PlayerShortcutCommand(
            kind="collection",
            player_id=None,
        )
    }

    asyncio.run(
        player_shortcuts.handle_player_shortcut(
            dependencies,
            cast("Any", object()),
            group_message_event("收集"),
            state,
        )
    )

    prompt.assert_awaited_once()
    service.shortcut.assert_not_awaited()
