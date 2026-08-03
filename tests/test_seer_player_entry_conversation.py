import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from ironsbot.config.player_accounts import PlayerAccount, PlayerAccountRegistry
from ironsbot.plugins.seer.query.commands import player, player_shortcuts
from ironsbot.plugins.seer.query.commands.player_context import (
    PLAYER_BINDING_NAMESPACE,
    PLAYER_DETAIL_NAMESPACE,
)
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_service import PendingPlayerQuery
from ironsbot.services.seer.player_shortcuts import PlayerShortcutCommand
from ironsbot.services.seer.query_result import QueryReply
from tests.helpers.onebot_events import group_message_event

_ACCOUNT_PLAYER_ID = 949105380


def test_player_conversation_flows_share_one_session() -> None:
    assert {
        PLAYER_BINDING_NAMESPACE,
        PLAYER_DETAIL_NAMESPACE,
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


def test_unbound_player_prompt_requires_an_explicit_full_player_id(
    monkeypatch: Any,
) -> None:
    finish_reply = AsyncMock()
    monkeypatch.setattr(player, "finish_event_reply", finish_reply)
    dependencies = player.PlayerCommandDependencies(
        cast("Any", object()),
        cast("Any", object()),
    )
    asyncio.run(
        player.prompt_for_unbound_player_id(
            dependencies,
            cast("Any", object()),
            group_message_event("收集"),
        )
    )

    call = finish_reply.await_args
    assert call is not None
    message = call.args[2]
    assert message == unbound_player_shortcut_message()


def test_binding_command_accepts_numeric_player_id() -> None:
    state: dict[str, object] = {}

    matched = asyncio.run(
        player._is_binding_command(group_message_event("绑定米米号949105380"), state)
    )

    assert matched is True
    assert state[player.BOT_COMMAND_ARG_KEY] == "949105380"


def test_binding_command_captures_invalid_player_id_for_error_reply() -> None:
    state: dict[str, object] = {}

    matched = asyncio.run(
        player._is_binding_command(group_message_event("绑定米米号abc"), state)
    )

    assert matched is True
    assert state[player.BOT_COMMAND_ARG_KEY] == "abc"


def test_player_commands_resolve_configured_account_names() -> None:
    registry = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=_ACCOUNT_PLAYER_ID,
                name="sample_player",
                aliases=("示例账号",),
                query_worker=False,
                password=None,
                public=True,
            ),
        )
    )
    service = SimpleNamespace(default_player_id=lambda _user_id: _ACCOUNT_PLAYER_ID)
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
        player_accounts=registry,
    )
    state: dict[str, object] = {}
    event = group_message_event("米米号示例账号")

    assert asyncio.run(player._is_player_id_query(event, state))
    asyncio.run(
        player.validate_player_id(
            dependencies,
            cast("Any", object()),
            event,
            cast("Any", state),
        )
    )
    assert state[player.PLAYER_ID_KEY] == _ACCOUNT_PLAYER_ID

    shortcut_state: dict[str, object] = {}
    assert asyncio.run(
        player_shortcuts._is_player_shortcut(
            group_message_event("收集sample_player"),
            shortcut_state,
            dependencies=dependencies,
        )
    )
    assert shortcut_state[player_shortcuts._SHORTCUT_COMMAND_KEY] == (
        PlayerShortcutCommand("collection", _ACCOUNT_PLAYER_ID)
    )

    peak_state: dict[str, object] = {}
    assert asyncio.run(
        player_shortcuts._is_player_shortcut(
            group_message_event("巅峰示例账号"),
            peak_state,
            dependencies=dependencies,
        )
    )
    assert peak_state[player_shortcuts._SHORTCUT_COMMAND_KEY] == (
        PlayerShortcutCommand("peak", _ACCOUNT_PLAYER_ID)
    )


def test_binding_command_rejects_account_aliases(monkeypatch: Any) -> None:
    finish_reply = AsyncMock()
    monkeypatch.setattr(player, "finish_event_reply", finish_reply)
    service = SimpleNamespace(bind_player=AsyncMock())
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )

    asyncio.run(
        player.handle_player_binding_command(
            dependencies,
            cast("Any", object()),
            group_message_event("绑定米米号示例账号"),
            {player.BOT_COMMAND_ARG_KEY: "示例账号"},
        )
    )

    call = finish_reply.await_args
    assert call is not None
    assert call.args[2].startswith("绑定米米号请直接填写数字")
    service.bind_player.assert_not_awaited()


def test_shortcut_without_default_shows_explicit_player_id_help(
    monkeypatch: Any,
) -> None:
    service = SimpleNamespace(
        default_player_id=lambda _user_id: None,
        shortcut=AsyncMock(return_value=QueryReply(text="尚未绑定米米号。")),
    )
    finish_reply = AsyncMock()
    monkeypatch.setattr(player_shortcuts, "finish_event_reply", finish_reply)
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

    service.shortcut.assert_awaited_once()
    finish_reply.assert_awaited_once()


def test_shortcut_sends_loading_reply_before_query(
    monkeypatch: Any,
) -> None:
    service = SimpleNamespace(
        default_player_id=lambda _user_id: 949105380,
        shortcut=AsyncMock(return_value=QueryReply(text="查询结果")),
    )
    loading_reply = AsyncMock()
    finish_reply = AsyncMock()
    monkeypatch.setattr(player_shortcuts, "send_event_reply", loading_reply)
    monkeypatch.setattr(player_shortcuts, "finish_event_reply", finish_reply)
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )
    event = group_message_event("巅峰")
    state: dict[str, object] = {
        player_shortcuts._SHORTCUT_COMMAND_KEY: PlayerShortcutCommand(
            kind="peak",
            player_id=None,
        )
    }

    asyncio.run(
        player_shortcuts.handle_player_shortcut(
            dependencies,
            cast("Any", object()),
            event,
            state,
        )
    )

    loading_reply.assert_awaited_once()
    loading_call = loading_reply.await_args
    assert loading_call is not None
    assert "巅峰之战正在查询" in loading_call.args[2]
    service.shortcut.assert_awaited_once_with(
        PlayerShortcutCommand(kind="peak", player_id=949105380),
        event.user_id,
        group_id=event.group_id,
    )
    finish_reply.assert_awaited_once()


def test_shortcut_semantic_request_uses_the_bound_player() -> None:
    service = SimpleNamespace(default_player_id=lambda _user_id: 712_345_678)
    event = group_message_event("收集")
    state: dict[str, object] = {
        player_shortcuts._SHORTCUT_COMMAND_KEY: PlayerShortcutCommand(
            kind="collection",
            player_id=None,
        )
    }

    request = player_shortcuts._shortcut_semantic_request(
        cast("Any", service),
        event,
        cast("Any", state),
    )

    assert request is not None
    assert (request.action.id, request.target.key) == (
        "seer.player.collection",
        "712345678",
    )
