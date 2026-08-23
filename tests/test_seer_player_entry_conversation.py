import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.config.player_accounts import PlayerAccount, PlayerAccountRegistry
from ironsbot.core.request_coordination import send_request_response
from ironsbot.core.semantic_requests import ActionDefinition
from ironsbot.plugins.seer.query.commands import (
    player,
    player_shortcuts,
    player_target_selection,
)
from ironsbot.plugins.seer.query.commands.player_context import (
    PLAYER_BINDING_NAMESPACE,
    PLAYER_DETAIL_NAMESPACE,
)
from ironsbot.plugins.seer.query.commands.player_target import (
    PlayerTargetResolution,
    protected_shortcut_target_error,
)
from ironsbot.runtime.prompts import Prompt
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message
from ironsbot.services.seer.player_service import PendingPlayerQuery, PlayerQueryResult
from ironsbot.services.seer.player_shortcuts import PlayerShortcutCommand
from ironsbot.services.seer.query_result import QueryReply
from tests.helpers.onebot_events import group_message_event, private_message_event

_ACCOUNT_PLAYER_ID = 949105380


def _features(*, superuser: bool = False) -> SimpleNamespace:
    return SimpleNamespace(is_superuser=lambda _user_id: superuser)


def test_player_conversation_flows_share_one_session() -> None:
    assert {
        PLAYER_BINDING_NAMESPACE,
        PLAYER_DETAIL_NAMESPACE,
    } == {PLAYER_DETAIL_NAMESPACE}


def test_superuser_binding_protection_only_applies_to_indirect_targets() -> None:
    service = SimpleNamespace(
        shortcut_target_access_error=lambda _user_id, _player_id: "已保护"
    )

    assert (
        protected_shortcut_target_error(
            service,
            10002,
            PlayerTargetResolution(_ACCOUNT_PLAYER_ID, offer_binding=True),
        )
        is None
    )
    assert protected_shortcut_target_error(
        service,
        10002,
        PlayerTargetResolution(
            _ACCOUNT_PLAYER_ID,
            offer_binding=False,
            is_shortcut_target=True,
        ),
    ) == "已保护"


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


def test_pending_binding_choice_accepts_an_optional_bot_mention() -> None:
    event = group_message_event(
        user_id=123,
        self_id=1,
        message=Message(MessageSegment.at(1) + MessageSegment.text(" y")),
    )

    assert player._parse_pending_binding_event(event, 949105380) is True


def test_pending_binding_choice_rejects_member_mentions() -> None:
    event = group_message_event(
        user_id=123,
        self_id=1,
        message=Message(MessageSegment.at(456) + MessageSegment.text(" 是")),
    )

    assert player._parse_pending_binding_event(event, 949105380) is None


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
        cast("Any", _features()),
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
        replacing_existing=False,
    )
    send_pending.assert_awaited_once_with(
        dependencies,
        matcher,
        event,
        state,
        pending,
    )


def test_binding_offer_keeps_its_confirmation_session_before_detail_menu(
    monkeypatch: Any,
) -> None:
    pending = PendingPlayerQuery(
        player_id=949105380,
        user_info=SimpleNamespace(nick="测试玩家"),
        more_info=object(),
        player_message="玩家详情",
        section_plan=cast("Any", object()),
    )
    service = SimpleNamespace(binding_offer=Mock(return_value="是否绑定"))
    enter_conversation = AsyncMock()
    send_pending = AsyncMock()
    monkeypatch.setattr(player, "enter_event_reply_conversation", enter_conversation)
    monkeypatch.setattr(player, "_send_pending_player_query", send_pending)
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", object()),
    )
    event = group_message_event("米米号123456")
    state: dict[str, object] = {}

    asyncio.run(
        player._handle_player_query_result(
            dependencies,
            cast("Any", object()),
            event,
            cast("Any", state),
            PlayerQueryResult(pending=pending, offer_binding=True),
        )
    )

    enter_conversation.assert_awaited_once()
    send_pending.assert_not_awaited()
    assert state[player.PLAYER_BINDING_PENDING_KEY] is pending
    call = enter_conversation.await_args
    assert call is not None
    options = call.kwargs
    assert options["reply_check"](
        group_message_event(
            user_id=event.user_id,
            self_id=1,
            message=Message(MessageSegment.at(1) + MessageSegment.text(" y")),
        )
    )
    assert not options["group_reply_check"](
        group_message_event(
            user_id=event.user_id + 1,
            self_id=1,
            message=Message(MessageSegment.at(1) + MessageSegment.text(" y")),
        )
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
    replacement = player.PlayerBindingState(10001, 777777, "旧账号")
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
        event.user_id,
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
        cast("Any", _features()),
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
        cast("Any", _features()),
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

    autocard_state: dict[str, object] = {}
    assert asyncio.run(
        player_shortcuts._is_player_shortcut(
            group_message_event("群星牌示例账号"),
            autocard_state,
            dependencies=dependencies,
        )
    )
    assert autocard_state[player_shortcuts._SHORTCUT_COMMAND_KEY] == (
        PlayerShortcutCommand("autocard", _ACCOUNT_PLAYER_ID)
    )


def test_player_query_prompts_for_ambiguous_partial_alias(
    monkeypatch: Any,
) -> None:
    other_player_id = 949105381
    registry = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=_ACCOUNT_PLAYER_ID,
                name="worker_one",
                aliases=("玩家1",),
                password=None,
                public=True,
            ),
            PlayerAccount(
                player_id=other_player_id,
                name="worker_two",
                aliases=("玩家2",),
                password=None,
                public=True,
            ),
        )
    )
    dependencies = player.PlayerCommandDependencies(
        cast("Any", SimpleNamespace(default_player_id=lambda _user_id: None)),
        cast("Any", _features()),
        player_accounts=registry,
    )
    enter_selection = AsyncMock()
    query_player = AsyncMock()
    monkeypatch.setattr(player_target_selection, "enter_prompt", enter_selection)
    monkeypatch.setattr(player, "handle_player", query_player)
    event = group_message_event("米米号玩家")
    state: dict[str, object] = {}

    assert asyncio.run(player._is_player_id_query(dependencies, event, state))
    asyncio.run(
        player.validate_player_id(
            dependencies,
            cast("Any", object()),
            event,
            cast("Any", state),
        )
    )

    call = enter_selection.await_args
    assert call is not None
    prompt = call.args[3]
    assert isinstance(prompt, Prompt)
    assert [(item.name, item.desc, item.value) for item in prompt.items] == [
        ("玩家1", f"游戏内ID：{_ACCOUNT_PLAYER_ID}", _ACCOUNT_PLAYER_ID),
        ("玩家2", f"游戏内ID：{other_player_id}", other_player_id),
    ]

    resolver = call.args[4]
    selected_state: dict[str, object] = {}
    selection_matcher = cast("Any", SimpleNamespace(state=selected_state))
    selection_event = group_message_event("2")
    asyncio.run(
        resolver(
            prompt.items[1],
            selection_matcher,
            selection_event,
        )
    )

    assert selected_state[player.PLAYER_ID_KEY] == other_player_id
    assert selected_state[player.PLAYER_QUERY_IS_EXPLICIT_KEY] is True
    query_player.assert_awaited_once_with(
        dependencies,
        selection_matcher,
        selection_event,
        selected_state,
    )


def test_player_shortcut_prompts_for_ambiguous_partial_alias(
    monkeypatch: Any,
) -> None:
    other_player_id = 949105381
    registry = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=_ACCOUNT_PLAYER_ID,
                name="worker_one",
                aliases=("玩家1",),
                password=None,
                public=True,
            ),
            PlayerAccount(
                player_id=other_player_id,
                name="worker_two",
                aliases=("玩家2",),
                password=None,
                public=True,
            ),
        )
    )
    dependencies = player.PlayerCommandDependencies(
        cast("Any", SimpleNamespace(default_player_id=lambda _user_id: None)),
        cast("Any", _features()),
        player_accounts=registry,
    )
    enter_selection = AsyncMock()
    query_shortcut = AsyncMock()
    monkeypatch.setattr(
        player_shortcuts,
        "enter_player_target_selection",
        enter_selection,
    )
    event = group_message_event("巅峰玩家")
    state: dict[str, object] = {}

    assert asyncio.run(
        player_shortcuts._is_player_shortcut(
            event,
            state,
            dependencies=dependencies,
        )
    )
    asyncio.run(
        player_shortcuts.handle_player_shortcut(
            dependencies,
            cast("Any", object()),
            event,
            cast("Any", state),
        )
    )

    call = enter_selection.await_args
    assert call is not None
    target = call.args[3]
    assert isinstance(target, player.PlayerTargetResolution)
    assert [choice.label for choice in target.choices] == ["玩家1", "玩家2"]

    select_target = call.args[4]
    selected_state: dict[str, object] = {}
    selection_matcher = cast("Any", SimpleNamespace(state=selected_state))
    selection_event = group_message_event("2")
    monkeypatch.setattr(
        player_shortcuts,
        "handle_player_shortcut",
        query_shortcut,
    )
    asyncio.run(
        select_target(other_player_id, selection_matcher, selection_event)
    )

    selected_command = selected_state[player_shortcuts._SHORTCUT_COMMAND_KEY]
    assert selected_command == PlayerShortcutCommand("peak", other_player_id)
    query_shortcut.assert_awaited_once_with(
        dependencies,
        selection_matcher,
        selection_event,
        selected_state,
    )

def test_player_query_ignores_unknown_natural_language_suffixes() -> None:
    dependencies = player.PlayerCommandDependencies(
        cast("Any", object()),
        cast("Any", _features()),
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
        cast("Any", object()),
        cast("Any", _features()),
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
        cast("Any", object()),
        cast("Any", _features()),
    )
    state: dict[str, object] = {}

    assert asyncio.run(
        player._is_player_id_query(
            dependencies,
            group_message_event("米米号12"),
            state,
        )
    )
    assert state[player.BOT_COMMAND_ARG_KEY] == "12"


def test_player_shortcut_ignores_unknown_account_suffix() -> None:
    dependencies = player.PlayerCommandDependencies(
        cast("Any", object()),
        cast("Any", _features()),
    )

    assert not asyncio.run(
        player_shortcuts._is_player_shortcut(
            group_message_event("收集未知别名"),
            {},
            dependencies=dependencies,
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
        cast("Any", object()),
        cast("Any", _features()),
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
    assert isinstance(command, player_shortcuts.PlayerExtensionShortcutCommand)
    assert command.player_id == _ACCOUNT_PLAYER_ID


def test_superuser_resolves_private_lineup_alias_outside_allowed_groups(
    monkeypatch: Any,
) -> None:
    accounts = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=_ACCOUNT_PLAYER_ID,
                name="private_player",
                aliases=("爱酱",),
                password=None,
                public=False,
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
        cast("Any", object()),
        cast("Any", _features(superuser=True)),
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
            group_message_event("阵容爱酱", group_id=987654321),
            state,
            dependencies=dependencies,
        )
    )
    command = state[player_shortcuts._EXTENSION_SHORTCUT_COMMAND_KEY]
    assert isinstance(command, player_shortcuts.PlayerExtensionShortcutCommand)
    assert command.player_id == _ACCOUNT_PLAYER_ID


def test_binding_command_accepts_visible_account_aliases(monkeypatch: Any) -> None:
    finish_reply = AsyncMock()
    monkeypatch.setattr(player, "finish_event_reply", finish_reply)
    service = SimpleNamespace(bind_player=AsyncMock())
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
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", _features()),
        player_accounts=registry,
    )

    asyncio.run(
        player.handle_player_binding_command(
            dependencies,
            cast("Any", object()),
            group_message_event("绑定米米号示例账号"),
            {player.BOT_COMMAND_ARG_KEY: "示例账号"},
        )
    )

    service.bind_player.assert_awaited_once_with(
        _ACCOUNT_PLAYER_ID,
        qq_user_id=123,
        group_id=456,
    )


def test_superuser_can_bind_a_mentioned_member(monkeypatch: Any) -> None:
    finish_reply = AsyncMock()
    monkeypatch.setattr(player, "finish_event_reply", finish_reply)
    bind_for_user = AsyncMock(return_value=PlayerQueryResult(message="已绑定"))
    monkeypatch.setattr(player, "bind_player_for_user", bind_for_user)
    service = SimpleNamespace(
        bind_player=AsyncMock(),
    )
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", _features(superuser=True)),
        player_accounts=cast(
            "Any",
            SimpleNamespace(resolve_player_id=lambda _value: _ACCOUNT_PLAYER_ID),
        ),
    )
    event = group_message_event(
        "绑定米米号949105380",
        user_id=10001,
        group_id=20002,
        message=Message(
            MessageSegment.text("绑定米米号949105380") + MessageSegment.at(30003)
        ),
    )

    asyncio.run(
        player.handle_player_binding_command(
            dependencies,
            cast("Any", object()),
            event,
            {player.BOT_COMMAND_ARG_KEY: "949105380"},
        )
    )

    bind_for_user.assert_awaited_once_with(
        service,
        _ACCOUNT_PLAYER_ID,
        actor_qq_user_id=10001,
        target_qq_user_id=30003,
        group_id=20002,
    )
    service.bind_player.assert_not_awaited()
    finish_reply.assert_awaited_once()


def test_superuser_can_bind_a_mentioned_member_by_private_alias(
    monkeypatch: Any,
) -> None:
    finish_reply = AsyncMock()
    monkeypatch.setattr(player, "finish_event_reply", finish_reply)
    bind_for_user = AsyncMock(return_value=PlayerQueryResult(message="已绑定"))
    monkeypatch.setattr(player, "bind_player_for_user", bind_for_user)
    service = SimpleNamespace(bind_player=AsyncMock())
    registry = PlayerAccountRegistry(
        (
            PlayerAccount(
                player_id=_ACCOUNT_PLAYER_ID,
                name="lineup_worker",
                aliases=("甲佬",),
                password=None,
                public=False,
            ),
        )
    )
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", _features(superuser=True)),
        player_accounts=registry,
    )
    event = group_message_event(
        "绑定米米号甲佬",
        user_id=10001,
        group_id=20002,
        message=Message(
            MessageSegment.text("绑定米米号甲佬") + MessageSegment.at(30003)
        ),
    )

    asyncio.run(
        player.handle_player_binding_command(
            dependencies,
            cast("Any", object()),
            event,
            {player.BOT_COMMAND_ARG_KEY: "甲佬"},
        )
    )

    bind_for_user.assert_awaited_once_with(
        service,
        _ACCOUNT_PLAYER_ID,
        actor_qq_user_id=10001,
        target_qq_user_id=30003,
        group_id=20002,
    )
    service.bind_player.assert_not_awaited()


def test_non_superuser_cannot_bind_a_mentioned_member(monkeypatch: Any) -> None:
    finish_reply = AsyncMock()
    monkeypatch.setattr(player, "finish_event_reply", finish_reply)
    service = SimpleNamespace(bind_player=AsyncMock())
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", _features()),
        player_accounts=cast(
            "Any",
            SimpleNamespace(resolve_player_id=lambda _value: _ACCOUNT_PLAYER_ID),
        ),
    )
    event = group_message_event(
        "绑定米米号949105380",
        message=Message(
            MessageSegment.text("绑定米米号949105380") + MessageSegment.at(30003)
        ),
    )

    asyncio.run(
        player.handle_player_binding_command(
            dependencies,
            cast("Any", object()),
            event,
            {player.BOT_COMMAND_ARG_KEY: "949105380"},
        )
    )

    service.bind_player.assert_not_awaited()
    call = finish_reply.await_args
    assert call is not None
    assert call.args[2] == "仅超级管理员可为其他成员绑定米米号。"


def test_superuser_cannot_bind_a_member_from_a_private_message(
    monkeypatch: Any,
) -> None:
    finish_reply = AsyncMock()
    monkeypatch.setattr(player, "finish_event_reply", finish_reply)
    service = SimpleNamespace(bind_player=AsyncMock())
    dependencies = player.PlayerCommandDependencies(
        cast("Any", service),
        cast("Any", _features(superuser=True)),
        player_accounts=cast(
            "Any",
            SimpleNamespace(resolve_player_id=lambda _value: _ACCOUNT_PLAYER_ID),
        ),
    )
    event = private_message_event("绑定米米号949105380")
    event.message = Message(
        MessageSegment.text("绑定米米号949105380") + MessageSegment.at(30003)
    )
    event.original_message = event.message

    asyncio.run(
        player.handle_player_binding_command(
            dependencies,
            cast("Any", object()),
            event,
            {player.BOT_COMMAND_ARG_KEY: "949105380"},
        )
    )

    service.bind_player.assert_not_awaited()
    call = finish_reply.await_args
    assert call is not None
    assert call.args[2] == "仅群聊可为成员绑定米米号。"


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
    async def shortcut(*_args: object, **_kwargs: object) -> QueryReply:
        await send_request_response(queued=False)
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


def test_shortcut_reports_when_the_first_packet_is_queued(
    monkeypatch: Any,
) -> None:
    async def shortcut(*_args: object, **_kwargs: object) -> QueryReply:
        await send_request_response(queued=True)
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
                player_shortcuts._SHORTCUT_COMMAND_KEY: PlayerShortcutCommand(
                    kind="collection",
                    player_id=None,
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
                player_shortcuts._SHORTCUT_COMMAND_KEY: PlayerShortcutCommand(
                    kind="autocard",
                    player_id=None,
                )
            },
        )
    )

    loading_reply.assert_not_awaited()


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
