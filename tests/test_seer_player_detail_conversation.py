from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from nonebot.exception import FinishedException

from ironsbot.plugins.seer.query.commands import player_detail_conversation
from ironsbot.plugins.seer.query.commands.player_context import (
    PLAYER_DETAIL_MENU_CONTEXT_KEY,
    PLAYER_ID_KEY,
    PlayerDetailMenuContext,
)
from ironsbot.runtime.prompt_sessions import (
    QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY,
)
from ironsbot.runtime.semantic_requests import ActionDefinition
from ironsbot.services.operations.request_feedback import send_request_feedback
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_query import (
    PLAYER_COLLECTION_KEY,
    PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY,
    PLAYER_DETAIL_COMMANDS_KEY,
    PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY,
    PLAYER_PEAK_KEY,
)
from ironsbot.services.seer.player_shortcuts import PlayerShortcutCommand
from ironsbot.services.seer.query_result import QueryReply
from tests.helpers.onebot_events import group_message_event

PLAYER_ID = 105_023_264
EXPECTED_CONVERSATION_CONTINUES = 2


def test_player_info_prompt_includes_visible_private_extension(
    monkeypatch: Any,
) -> None:
    enter_conversation = AsyncMock(side_effect=FinishedException)
    monkeypatch.setattr(
        player_detail_conversation,
        "enter_event_reply_conversation",
        enter_conversation,
    )
    monkeypatch.setattr(
        player_detail_conversation,
        "event_is_feature_allowed",
        lambda *_args: True,
    )
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(
        PlayerDetailExtensionAction(
            id="private_action",
            feature="private_feature",
            label="private action",
            aliases=("private",),
            command_help_id="private.action",
            query=AsyncMock(return_value=QueryReply(text="private reply")),
            action=ActionDefinition("private_action", "private action"),
        )
    )
    state: dict[str, object] = {}

    with suppress(FinishedException):
        asyncio.run(
            player_detail_conversation.send_player_info_with_detail_prompt(
                cast("Any", object()),
                cast("Any", object()),
                extensions,
                cast("Any", object()),
                group_message_event("player712345678"),
                cast("Any", state),
                player_id=PLAYER_ID,
                player_message="player",
                has_collection=True,
            )
        )
    call = enter_conversation.await_args
    assert call is not None
    assert "2.【private action】" in call.kwargs["prompt"]
    assert state[PLAYER_DETAIL_COMMANDS_KEY] == (
        "1",
        "2",
        "0",
    )
    assert state[PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY] == (
        ("1", PLAYER_COLLECTION_KEY),
    )
    assert state[PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY] == (
        ("2", "private_action"),
    )


def test_player_detail_uses_the_shared_shortcut_executor(
    monkeypatch: Any,
) -> None:
    async def shortcut(*_args: object, **_kwargs: object) -> QueryReply:
        await send_request_feedback(queued=False)
        return QueryReply(text="peak")

    service = SimpleNamespace(shortcut=AsyncMock(side_effect=shortcut))
    continue_conversation = AsyncMock()
    monkeypatch.setattr(
        player_detail_conversation,
        "_continue_player_detail_conversation",
        continue_conversation,
    )
    send_status = AsyncMock()
    monkeypatch.setattr(player_detail_conversation, "send_event_reply", send_status)
    event = group_message_event("2")
    state: dict[str, object] = {
        PLAYER_ID_KEY: PLAYER_ID,
        PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY: (("2", PLAYER_PEAK_KEY),),
    }

    asyncio.run(
        player_detail_conversation.handle_player_detail_reply(
            cast("Any", service),
            PlayerDetailExtensionRegistry(),
            cast("Any", object()),
            cast("Any", object()),
            event,
            cast("Any", state),
        )
    )

    service.shortcut.assert_awaited_once_with(
        PlayerShortcutCommand(kind="peak", player_id=PLAYER_ID),
        event.user_id,
        group_id=event.group_id,
    )
    asyncio.run(
        player_detail_conversation.handle_player_detail_reply(
            cast("Any", service),
            PlayerDetailExtensionRegistry(),
            cast("Any", object()),
            cast("Any", object()),
            event,
            cast("Any", state),
        )
    )

    assert service.shortcut.await_count == EXPECTED_CONVERSATION_CONTINUES
    assert continue_conversation.await_count == EXPECTED_CONVERSATION_CONTINUES
    assert send_status.await_count == EXPECTED_CONVERSATION_CONTINUES
    assert all(
        call.args[2] == "⏳ 巅峰之战正在查询，完成后会直接发送结果。"
        for call in send_status.await_args_list
    )


def test_player_detail_uses_the_replying_member_for_shared_menu_actions(
    monkeypatch: Any,
) -> None:
    service = SimpleNamespace(
        shortcut=AsyncMock(return_value=QueryReply(text="collection"))
    )
    monkeypatch.setattr(
        player_detail_conversation,
        "_continue_player_detail_conversation",
        AsyncMock(),
    )
    monkeypatch.setattr(
        player_detail_conversation,
        "send_event_reply",
        AsyncMock(),
    )
    replying_member = group_message_event("1", user_id=456_789)
    state: dict[str, object] = {
        PLAYER_ID_KEY: PLAYER_ID,
        PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY: (("1", PLAYER_COLLECTION_KEY),),
    }

    asyncio.run(
        player_detail_conversation.handle_player_detail_reply(
            cast("Any", service),
            PlayerDetailExtensionRegistry(),
            cast("Any", object()),
            cast("Any", object()),
            replying_member,
            cast("Any", state),
        )
    )

    service.shortcut.assert_awaited_once_with(
        PlayerShortcutCommand(kind="collection", player_id=PLAYER_ID),
        replying_member.user_id,
        group_id=replying_member.group_id,
    )


def test_shared_player_menu_reply_creates_the_replying_members_context(
    monkeypatch: Any,
) -> None:
    class PromptSessions:
        def detach_queued_conversation(self, state: dict[str, object]) -> None:
            state.pop(QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY, None)

    service = SimpleNamespace(
        shortcut=AsyncMock(return_value=QueryReply(text="collection"))
    )
    continue_conversation = AsyncMock()
    monkeypatch.setattr(
        player_detail_conversation,
        "get_prompt_session_manager",
        lambda _matcher: PromptSessions(),
    )
    monkeypatch.setattr(
        player_detail_conversation,
        "_continue_player_detail_conversation",
        continue_conversation,
    )
    monkeypatch.setattr(player_detail_conversation, "send_event_reply", AsyncMock())
    features = SimpleNamespace(
        is_group_feature_allowed=lambda *_args: True,
    )
    event = group_message_event("1", user_id=456_789)
    state: dict[str, object] = {
        QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY: True,
        PLAYER_ID_KEY: PLAYER_ID,
        PLAYER_DETAIL_MENU_CONTEXT_KEY: PlayerDetailMenuContext(
            player_id=PLAYER_ID,
            has_collection=True,
            has_peak=False,
            has_autocard=False,
        ),
        PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY: (("1", PLAYER_COLLECTION_KEY),),
    }

    asyncio.run(
        player_detail_conversation.handle_player_detail_reply(
            cast("Any", service),
            PlayerDetailExtensionRegistry(),
            cast("Any", features),
            cast("Any", object()),
            event,
            cast("Any", state),
        )
    )

    service.shortcut.assert_awaited_once_with(
        PlayerShortcutCommand(kind="collection", player_id=PLAYER_ID),
        event.user_id,
        group_id=event.group_id,
    )
    assert state[PLAYER_ID_KEY] == PLAYER_ID
    assert state[PLAYER_DETAIL_COMMANDS_KEY] == ("1", "0")
    continue_conversation.assert_awaited_once()


def test_shared_player_menu_exit_only_exits_the_replying_member(
    monkeypatch: Any,
) -> None:
    class PromptSessions:
        def detach_queued_conversation(self, state: dict[str, object]) -> None:
            state.pop(QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY, None)

    finish_reply = AsyncMock()
    monkeypatch.setattr(
        player_detail_conversation,
        "get_prompt_session_manager",
        lambda _matcher: PromptSessions(),
    )
    monkeypatch.setattr(player_detail_conversation, "finish_event_reply", finish_reply)
    features = SimpleNamespace(is_group_feature_allowed=lambda *_args: True)
    event = group_message_event("0", user_id=456_789)
    matcher = cast("Any", object())
    state: dict[str, object] = {
        QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY: True,
        PLAYER_DETAIL_MENU_CONTEXT_KEY: PlayerDetailMenuContext(
            player_id=PLAYER_ID,
            has_collection=True,
            has_peak=False,
            has_autocard=False,
        ),
        PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY: (("1", PLAYER_COLLECTION_KEY),),
    }

    asyncio.run(
        player_detail_conversation.handle_player_detail_reply(
            cast("Any", object()),
            PlayerDetailExtensionRegistry(),
            cast("Any", features),
            matcher,
            event,
            cast("Any", state),
        )
    )

    finish_reply.assert_awaited_once_with(
        matcher,
        event,
        "已退出米米号详情查询。",
    )


def test_shared_player_menu_cannot_use_an_extension_hidden_from_the_replying_member(
    monkeypatch: Any,
) -> None:
    class PromptSessions:
        def detach_queued_conversation(self, state: dict[str, object]) -> None:
            state.pop(QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY, None)

    action_query = AsyncMock(return_value=QueryReply(text="private reply"))
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(
        PlayerDetailExtensionAction(
            id="private_action",
            feature="private_feature",
            label="private action",
            aliases=("private",),
            command_help_id="private.action",
            query=action_query,
            action=ActionDefinition("private_action", "private action"),
        )
    )
    finish_reply = AsyncMock()
    monkeypatch.setattr(
        player_detail_conversation,
        "get_prompt_session_manager",
        lambda _matcher: PromptSessions(),
    )
    monkeypatch.setattr(player_detail_conversation, "finish_event_reply", finish_reply)
    features = SimpleNamespace(
        is_group_feature_allowed=lambda _user_id, _group_id, feature: (
            feature == "seer_player"
        )
    )
    event = group_message_event("2", user_id=456_789)
    matcher = cast("Any", object())
    state: dict[str, object] = {
        QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY: True,
        PLAYER_DETAIL_MENU_CONTEXT_KEY: PlayerDetailMenuContext(
            player_id=PLAYER_ID,
            has_collection=True,
            has_peak=False,
            has_autocard=False,
        ),
        PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY: (("1", PLAYER_COLLECTION_KEY),),
        PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY: (("2", "private_action"),),
    }

    asyncio.run(
        player_detail_conversation.handle_player_detail_reply(
            cast("Any", object()),
            extensions,
            cast("Any", features),
            matcher,
            event,
            cast("Any", state),
        )
    )

    action_query.assert_not_awaited()
    finish_reply.assert_awaited_once_with(matcher, event, "该功能当前未对你开放。")


def test_player_detail_delegates_a_registered_private_action(
    monkeypatch: Any,
) -> None:
    async def query(*_args: object) -> QueryReply:
        await send_request_feedback(queued=True)
        return QueryReply(text="private reply")

    action_query = AsyncMock(side_effect=query)
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(
        PlayerDetailExtensionAction(
            id="private_action",
            feature="private_feature",
            label="private action",
            aliases=("private",),
            command_help_id="private.action",
            query=action_query,
            action=ActionDefinition("private_action", "private action"),
        )
    )
    continue_conversation = AsyncMock()
    monkeypatch.setattr(
        player_detail_conversation,
        "_continue_player_detail_conversation",
        continue_conversation,
    )
    send_status = AsyncMock()
    monkeypatch.setattr(player_detail_conversation, "send_event_reply", send_status)
    event = group_message_event("1")
    state: dict[str, object] = {
        PLAYER_ID_KEY: PLAYER_ID,
        PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY: (("1", "private_action"),),
    }

    asyncio.run(
        player_detail_conversation.handle_player_detail_reply(
            cast("Any", object()),
            extensions,
            cast("Any", object()),
            cast("Any", object()),
            event,
            cast("Any", state),
        )
    )

    action_query.assert_awaited_once_with(PLAYER_ID, event.user_id, event.group_id)
    call = continue_conversation.await_args
    assert call is not None
    assert call.kwargs["prompt"] == "private reply"
    send_status.assert_awaited_once()
    status_call = send_status.await_args
    assert status_call is not None
    assert status_call.args[2] == (
        "⏳ 已收到：private action，已加入队列，完成后会直接发送结果。"
    )


def test_player_detail_semantic_request_matches_direct_shortcuts() -> None:
    event = group_message_event("1")
    state: dict[str, object] = {
        PLAYER_ID_KEY: PLAYER_ID,
        PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY: (("1", PLAYER_COLLECTION_KEY),),
    }

    request = player_detail_conversation._player_detail_semantic_request(
        PlayerDetailExtensionRegistry(),
        cast("Any", object()),
        event,
        cast("Any", state),
    )

    assert request is not None
    assert (request.action.id, request.target.key) == (
        "seer.player.collection",
        str(PLAYER_ID),
    )


def test_player_detail_extension_declares_a_semantic_action() -> None:
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(
        PlayerDetailExtensionAction(
            id="private_action",
            feature="private_feature",
            label="private action",
            aliases=("private",),
            command_help_id="private.action",
            query=AsyncMock(),
            action=ActionDefinition("private_action", "阵容"),
        )
    )
    event = group_message_event("1")
    state: dict[str, object] = {
        PLAYER_ID_KEY: PLAYER_ID,
        PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY: (("1", "private_action"),),
    }

    request = player_detail_conversation._player_detail_semantic_request(
        extensions,
        cast("Any", object()),
        event,
        cast("Any", state),
    )

    assert request is not None
    assert (request.action.id, request.target.key) == (
        "private_action",
        str(PLAYER_ID),
    )
