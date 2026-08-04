import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.config.player_accounts import PlayerAccount, PlayerAccountRegistry
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.plugins.onebot.seer.query.commands import player, player_shortcuts
from ironsbot.plugins.onebot.seer.query.commands.player_context import (
    PLAYER_BINDING_NAMESPACE,
    PLAYER_DETAIL_NAMESPACE,
)
from ironsbot.services.operations.request_feedback import send_request_feedback
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolution
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_service import PendingPlayerQuery
from ironsbot.services.seer.player_shortcuts import PlayerShortcutCommand
from ironsbot.services.seer.query_result import QueryReply
from tests.helpers.onebot_events import group_message_event

_ACCOUNT_PLAYER_ID = 949105380


def _actor(user_id: int) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


def test_player_conversation_flows_share_one_session() -> None:
    assert {
        PLAYER_BINDING_NAMESPACE,
        PLAYER_DETAIL_NAMESPACE,
    } == {PLAYER_DETAIL_NAMESPACE}


def test_pending_binding_choice_accepts_only_confirmation_replies() -> None:
    assert player._parse_pending_binding_choice("是", 949105380) is True
    assert player._parse_pending_binding_choice("n", 949105380) is False
    assert (
        player._parse_pending_binding_choice("绑定米米号949105380", 949105380) is None
    )
    assert (
        player._parse_pending_binding_choice("更改米米号949105380", 949105380) is None
    )
    assert player._parse_pending_binding_choice("绑定米米号123456", 949105380) is None


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
        _actor(event.user_id),
        pending,
        accepted=True,
        replacing_existing=False,
    )
    send_pending.assert_awaited_once_with(
        dependencies,
        matcher,
        event,
        state,
        pending,
    )


def test_pending_replacement_confirmation_marks_the_existing_binding(
    monkeypatch: Any,
) -> None:
    pending = PendingPlayerQuery(
        player_id=949105380,
        user_info=SimpleNamespace(nick="测试玩家"),
        more_info=object(),
        player_message="玩家详情",
        section_plan=cast("Any", object()),
    )
    replacement = player.PlayerBindingState(_actor(10001), 777777, "旧账号")
    service = SimpleNamespace(save_binding_choice=Mock())
    send_pending = AsyncMock()
    monkeypatch.setattr(player, "_send_pending_player_query", send_pending)
    event = group_message_event("否")
    state: dict[str, object] = {
        player.PLAYER_BINDING_PENDING_KEY: pending,
        player.PLAYER_BINDING_REPLACEMENT_KEY: replacement,
    }
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )

    asyncio.run(
        player.handle_player_binding_choice(
            dependencies,
            cast("Any", object()),
            event,
            cast("Any", state),
        )
    )

    service.save_binding_choice.assert_called_once_with(
        _actor(event.user_id),
        pending,
        accepted=False,
        replacing_existing=True,
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

    assert asyncio.run(player._is_player_id_query(dependencies, event, state))
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
        player_shortcuts._ResolvedShortcutCommand(
            PlayerShortcutCommand("collection", _ACCOUNT_PLAYER_ID)
        )
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
        player_shortcuts._ResolvedShortcutCommand(
            PlayerShortcutCommand("peak", _ACCOUNT_PLAYER_ID)
        )
    )

    autocard_state: dict[str, object] = {}
    assert asyncio.run(
        player_shortcuts._is_player_shortcut(
            group_message_event("群星牌示例账号"),
            autocard_state,
            dependencies=dependencies,
        )
    )
    assert autocard_state[player_shortcuts._SHORTCUT_COMMAND_KEY] == (
        player_shortcuts._ResolvedShortcutCommand(
            PlayerShortcutCommand("autocard", _ACCOUNT_PLAYER_ID)
        )
    )


def test_player_query_reuses_target_resolved_during_matcher_admission(
    monkeypatch: Any,
) -> None:
    resolved_target = PlayerIdResolution(_ACCOUNT_PLAYER_ID, offer_binding=True)
    resolve_target = Mock(return_value=resolved_target)
    monkeypatch.setattr(player, "resolve_player_target", resolve_target)
    dependencies = player.PlayerCommandDependencies(
        cast("Any", SimpleNamespace(default_player_id=lambda _actor: None)),
        cast("Any", object()),
    )
    state: dict[str, object] = {}
    event = group_message_event(f"米米号{_ACCOUNT_PLAYER_ID}")

    assert asyncio.run(player._is_player_id_query(dependencies, event, state))
    asyncio.run(
        player.validate_player_id(
            dependencies,
            cast("Any", object()),
            event,
            cast("Any", state),
        )
    )

    resolve_target.assert_called_once()
    assert state[player.PLAYER_ID_KEY] == _ACCOUNT_PLAYER_ID


def test_player_query_ignores_unknown_natural_language_suffixes() -> None:
    dependencies = player.PlayerCommandDependencies(
        cast("Any", SimpleNamespace(default_player_id=lambda _actor: None)),
        cast("Any", object()),
    )

    assert not asyncio.run(
        player._is_player_id_query(
            dependencies,
            group_message_event("米米号是多少"),
            {},
        )
    )
    assert not asyncio.run(
        player._is_player_id_query(
            dependencies,
            group_message_event("米米号未知别名"),
            {},
        )
    )


def test_player_query_with_member_at_does_not_accept_natural_language() -> None:
    dependencies = player.PlayerCommandDependencies(
        cast("Any", SimpleNamespace(default_player_id=lambda _actor: None)),
        cast("Any", object()),
    )
    event = group_message_event(
        "米米号是多少",
        message=Message(
            MessageSegment.at(456789)
            + MessageSegment.text(" 米米号是多少")
        ),
    )

    assert not asyncio.run(player._is_player_id_query(dependencies, event, {}))


def test_player_query_keeps_out_of_range_numeric_targets_for_validation() -> None:
    dependencies = player.PlayerCommandDependencies(
        cast("Any", SimpleNamespace(default_player_id=lambda _actor: None)),
        cast("Any", object()),
    )
    state: dict[str, object] = {}

    assert asyncio.run(
        player._is_player_id_query(
            dependencies,
            group_message_event("米米号12"),
            state,
        )
    )
    target = state[player.PLAYER_TARGET_RESOLUTION_KEY]
    assert isinstance(target, PlayerIdResolution)
    assert target.player_id is None
    assert target.error == "未找到该米米号或已开放的玩家别名。"


def test_player_shortcut_reports_an_unknown_account_suffix() -> None:
    dependencies = player.PlayerCommandDependencies(
        cast("Any", SimpleNamespace(default_player_id=lambda _actor: None)),
        cast("Any", object()),
    )

    state: dict[str, object] = {}
    assert asyncio.run(
        player_shortcuts._is_player_shortcut(
            group_message_event("收集未知别名"),
            state,
            dependencies=dependencies,
        )
    )
    assert state[player_shortcuts._SHORTCUT_COMMAND_KEY] == (
        player_shortcuts._ResolvedShortcutCommand(
            None,
            "未找到该米米号或已开放的玩家别名。",
        )
    )


def test_extension_shortcut_resolves_account_alias_in_public_command_layer(
    monkeypatch: Any,
) -> None:
    accounts = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=_ACCOUNT_PLAYER_ID,
                name="sample_player",
                aliases=("示例账号",),
                password=None,
                public=True,
            ),
        )
    )
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(
        PlayerDetailExtensionAction(
            id="private_lineup",
            feature="player_lineup_private",
            label="阵容",
            aliases=("阵容",),
            command_help_id="private_player_lineup.query",
            query=AsyncMock(return_value=QueryReply(text="ok")),
            action=ActionDefinition("private_lineup", "阵容"),
        )
    )
    dependencies = player.PlayerCommandDependencies(
        cast("Any", SimpleNamespace(default_player_id=lambda _actor: None)),
        cast("Any", object()),
        extensions,
        accounts,
    )
    monkeypatch.setattr(
        player_shortcuts,
        "event_is_feature_allowed",
        lambda *_args: True,
    )
    state: dict[str, object] = {}

    assert asyncio.run(
        player_shortcuts._is_player_extension_shortcut(
            group_message_event("阵容示例账号"),
            state,
            dependencies=dependencies,
        )
    )
    command = state[player_shortcuts._EXTENSION_SHORTCUT_COMMAND_KEY]
    assert isinstance(
        command,
        player_shortcuts._ResolvedExtensionShortcutCommand,
    )
    assert command.command is not None
    assert command.command.player_id == _ACCOUNT_PLAYER_ID


def test_binding_command_resolves_account_aliases(monkeypatch: Any) -> None:
    service = SimpleNamespace(
        bind_player=AsyncMock(),
        default_player_id=lambda _actor: None,
    )
    send_result = AsyncMock()
    monkeypatch.setattr(player, "_handle_player_query_result", send_result)
    registry = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=_ACCOUNT_PLAYER_ID,
                name="sample_player",
                aliases=("示例账号",),
                password=None,
                public=True,
            ),
        )
    )
    service.bind_player.return_value = cast("Any", object())
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
        player_accounts=registry,
    )
    event = group_message_event("绑定米米号示例账号")

    asyncio.run(
        player.handle_player_binding_command(
            dependencies,
            cast("Any", object()),
            event,
            {player.BOT_COMMAND_ARG_KEY: "示例账号"},
        )
    )

    service.bind_player.assert_awaited_once_with(
        _ACCOUNT_PLAYER_ID,
        actor=_actor(event.user_id),
        group_id=event.group_id,
    )


def test_binding_command_resolves_one_directly_mentioned_member(
    monkeypatch: Any,
) -> None:
    service = SimpleNamespace(
        bind_player=AsyncMock(),
        default_player_id=lambda actor: (
            _ACCOUNT_PLAYER_ID if actor.id == "456789" else None
        ),
    )
    monkeypatch.setattr(player, "_handle_player_query_result", AsyncMock())
    event = group_message_event(
        "绑定米米号",
        message=Message(MessageSegment.at(456789) + MessageSegment.text("绑定米米号")),
    )
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )
    service.bind_player.return_value = cast("Any", object())

    asyncio.run(
        player.handle_player_binding_command(
            dependencies,
            cast("Any", object()),
            event,
            {player.BOT_COMMAND_ARG_KEY: ""},
        )
    )

    service.bind_player.assert_awaited_once_with(
        _ACCOUNT_PLAYER_ID,
        actor=_actor(event.user_id),
        group_id=event.group_id,
    )


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
        player_shortcuts._SHORTCUT_COMMAND_KEY: (
            player_shortcuts._ResolvedShortcutCommand(
                None,
                "尚未绑定米米号，发送“绑定米米号123456”后，即可使用快捷指令。\n"
                "需要在查询指令后加上米米号，才能查询未绑定的米米号。",
            )
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

    service.shortcut.assert_not_awaited()
    finish_reply.assert_awaited_once()
    call = finish_reply.await_args
    assert call is not None
    assert call.args[2] == (
        "尚未绑定米米号，发送“绑定米米号123456”后，即可使用快捷指令。\n"
        "需要在查询指令后加上米米号，才能查询未绑定的米米号。"
    )


def test_shortcut_sends_loading_reply_before_query(
    monkeypatch: Any,
) -> None:
    async def shortcut(*_args: object, **_kwargs: object) -> QueryReply:
        await send_request_feedback(queued=False)
        return QueryReply(text="查询结果")

    service = SimpleNamespace(
        default_player_id=lambda _user_id: 949105380,
        shortcut=AsyncMock(side_effect=shortcut),
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
        player_shortcuts._SHORTCUT_COMMAND_KEY: (
            player_shortcuts._ResolvedShortcutCommand(
                PlayerShortcutCommand(kind="peak", player_id=949105380)
            )
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
        _actor(event.user_id),
        group_id=event.group_id,
    )
    finish_reply.assert_awaited_once()


def test_shortcut_reports_when_the_first_packet_is_queued(
    monkeypatch: Any,
) -> None:
    async def shortcut(*_args: object, **_kwargs: object) -> QueryReply:
        await send_request_feedback(queued=True)
        return QueryReply(text="查询结果")

    service = SimpleNamespace(
        default_player_id=lambda _user_id: 949105380,
        shortcut=AsyncMock(side_effect=shortcut),
    )
    loading_reply = AsyncMock()
    monkeypatch.setattr(player_shortcuts, "send_event_reply", loading_reply)
    monkeypatch.setattr(player_shortcuts, "finish_event_reply", AsyncMock())
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )

    asyncio.run(
        player_shortcuts.handle_player_shortcut(
            dependencies,
            cast("Any", object()),
            group_message_event("收集"),
            {
                player_shortcuts._SHORTCUT_COMMAND_KEY: (
                    player_shortcuts._ResolvedShortcutCommand(
                        PlayerShortcutCommand(
                            kind="collection",
                            player_id=949105380,
                        )
                    )
                )
            },
        )
    )

    loading_reply.assert_awaited_once()
    call = loading_reply.await_args
    assert call is not None
    assert call.args[2] == (
        "⏳ 已收到：收集与排行，已加入队列，完成后会直接发送结果。"
    )


def test_shortcut_cache_hit_does_not_send_loading_reply(
    monkeypatch: Any,
) -> None:
    service = SimpleNamespace(
        default_player_id=lambda _user_id: 949105380,
        shortcut=AsyncMock(return_value=QueryReply(text="缓存结果")),
    )
    loading_reply = AsyncMock()
    monkeypatch.setattr(player_shortcuts, "send_event_reply", loading_reply)
    monkeypatch.setattr(player_shortcuts, "finish_event_reply", AsyncMock())
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )

    asyncio.run(
        player_shortcuts.handle_player_shortcut(
            dependencies,
            cast("Any", object()),
            group_message_event("群星牌"),
            {
                player_shortcuts._SHORTCUT_COMMAND_KEY: (
                    player_shortcuts._ResolvedShortcutCommand(
                        PlayerShortcutCommand(
                            kind="autocard",
                            player_id=949105380,
                        )
                    )
                )
            },
        )
    )

    loading_reply.assert_not_awaited()


def test_shortcut_semantic_request_uses_the_bound_player() -> None:
    service = SimpleNamespace()
    dependencies = player_shortcuts.PlayerCommandDependencies(
        player=cast("Any", service),
        features=cast("Any", SimpleNamespace()),
    )
    event = group_message_event("收集")
    state: dict[str, object] = {
        player_shortcuts._SHORTCUT_COMMAND_KEY: (
            player_shortcuts._ResolvedShortcutCommand(
                PlayerShortcutCommand(
                    kind="collection",
                    player_id=712_345_678,
                )
            )
        )
    }

    request = player_shortcuts._shortcut_semantic_request(
        dependencies,
        event,
        cast("Any", state),
    )

    assert request is not None
    assert (request.action.id, request.target.key) == (
        "seer.player.collection",
        "712345678",
    )
