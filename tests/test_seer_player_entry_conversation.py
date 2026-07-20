import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from ironsbot.plugins.seer.query.commands import player, player_shortcuts
from ironsbot.services.seer.player_shortcuts import PlayerShortcutCommand
from tests.helpers.onebot_events import group_message_event


def test_unbound_player_entry_only_accepts_bare_numeric_ids() -> None:
    assert player._is_unbound_player_id_reply(group_message_event("949105380"))
    assert player._is_unbound_player_id_reply(group_message_event(" 949105380 "))
    assert not player._is_unbound_player_id_reply(
        group_message_event("米米号949105380")
    )
    assert not player._is_unbound_player_id_reply(group_message_event("949105380a"))


def test_unbound_player_entry_prompt_explains_bare_id_input() -> None:
    prompt = player._unbound_player_entry_prompt("❌ 米米号 949105380 查询失败：不存在")

    assert "直接发送米米号数字" in prompt
    assert "绑定米米号123456" in prompt
    assert "949105380 查询失败" in prompt
    assert "首次成功查询后" in prompt


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

    asyncio.run(
        player.handle_unbound_player_id_entry(
            cast("Any", service),
            cast("Any", object()),
            group_message_event("949105380"),
            {},
        )
    )

    service.query.assert_awaited_once_with(
        949105380,
        qq_user_id=123,
        explicit=True,
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

    asyncio.run(
        player.handle_unbound_player_id_entry(
            cast("Any", service),
            matcher,
            event,
            state,
        )
    )

    service.query.assert_awaited_once_with(
        949105380,
        qq_user_id=event.user_id,
        explicit=True,
    )
    handle_result.assert_awaited_once_with(
        service,
        matcher,
        event,
        state,
        result,
    )


def test_shortcut_without_default_opens_player_id_entry(
    monkeypatch: Any,
) -> None:
    service = SimpleNamespace(
        default_player_id=lambda _user_id: None,
        shortcut=AsyncMock(),
    )
    prompt = AsyncMock()
    monkeypatch.setattr(player_shortcuts, "prompt_for_unbound_player_id", prompt)
    state: dict[str, object] = {
        player_shortcuts._SHORTCUT_COMMAND_KEY: PlayerShortcutCommand(
            kind="collection",
            player_id=None,
        )
    }

    asyncio.run(
        player_shortcuts.handle_player_shortcut(
            cast("Any", service),
            cast("Any", object()),
            group_message_event("收集"),
            state,
        )
    )

    prompt.assert_awaited_once()
    service.shortcut.assert_not_awaited()
