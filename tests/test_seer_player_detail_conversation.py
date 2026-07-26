from __future__ import annotations

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from nonebot.exception import FinishedException

from ironsbot.plugins.seer.query.commands import player_detail_conversation
from ironsbot.plugins.seer.query.commands.player_context import PLAYER_ID_KEY
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
            query=AsyncMock(return_value=QueryReply(text="private reply")),
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
                group_message_event("player105023264"),
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
        "收集",
        "2",
        "private",
        "0",
    )
    assert state[PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY] == (
        ("1", PLAYER_COLLECTION_KEY),
    )
    assert state[PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY] == (
        ("2", "private_action"),
    )


def test_player_detail_fetches_a_builtin_section_once_per_conversation(
    monkeypatch: Any,
) -> None:
    service = SimpleNamespace(shortcut=AsyncMock(return_value=QueryReply(text="peak")))
    continue_conversation = AsyncMock()
    monkeypatch.setattr(
        player_detail_conversation,
        "_continue_player_detail_conversation",
        continue_conversation,
    )
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
            event,
            cast("Any", state),
        )
    )

    service.shortcut.assert_awaited_once_with(
        PlayerShortcutCommand(kind="peak", player_id=PLAYER_ID),
        event.user_id,
        group_id=event.group_id,
    )
    assert state[PLAYER_PEAK_KEY] == "peak"

    asyncio.run(
        player_detail_conversation.handle_player_detail_reply(
            cast("Any", service),
            PlayerDetailExtensionRegistry(),
            cast("Any", object()),
            event,
            cast("Any", state),
        )
    )

    service.shortcut.assert_awaited_once()
    assert continue_conversation.await_count == EXPECTED_CONVERSATION_CONTINUES


def test_player_detail_delegates_a_registered_private_action(
    monkeypatch: Any,
) -> None:
    action_query = AsyncMock(return_value=QueryReply(text="private reply"))
    extensions = PlayerDetailExtensionRegistry()
    extensions.register(
        PlayerDetailExtensionAction(
            id="private_action",
            feature="private_feature",
            label="private action",
            aliases=("private",),
            query=action_query,
        )
    )
    continue_conversation = AsyncMock()
    monkeypatch.setattr(
        player_detail_conversation,
        "_continue_player_detail_conversation",
        continue_conversation,
    )
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
            event,
            cast("Any", state),
        )
    )

    action_query.assert_awaited_once_with(PLAYER_ID, event.user_id, event.group_id)
    call = continue_conversation.await_args
    assert call is not None
    assert call.kwargs["prompt"] == "private reply"
