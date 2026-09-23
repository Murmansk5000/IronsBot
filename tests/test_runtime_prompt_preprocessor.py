import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from ironsbot.integrations.onebot import prompts
from ironsbot.integrations.onebot.matcher_support import EXPLICIT_COMMAND_STATE_KEY


def test_explicit_command_preprocessor_closes_active_conversations(
    monkeypatch: Any,
) -> None:
    manager = SimpleNamespace(
        invalidate_event_conversations=Mock(),
        invalidate=Mock(),
    )

    monkeypatch.setattr(prompts, "get_prompt_session_manager", lambda _matcher: manager)

    event = SimpleNamespace(get_session_id=lambda: "group_1_user_2")
    matcher = SimpleNamespace(state={EXPLICIT_COMMAND_STATE_KEY: True})

    async def invoke_preprocessor() -> None:
        await prompts._invalidate_prompt_on_command(matcher, event)

    asyncio.run(invoke_preprocessor())

    manager.invalidate.assert_called_once_with("bot::group_1_user_2")
    manager.invalidate_event_conversations.assert_called_once_with(event)


def test_menu_input_does_not_close_active_conversations(
    monkeypatch: Any,
) -> None:
    manager = SimpleNamespace(
        invalidate_event_conversations=Mock(),
        invalidate=Mock(),
    )
    monkeypatch.setattr(prompts, "get_prompt_session_manager", lambda _matcher: manager)

    event = SimpleNamespace(get_session_id=lambda: "group_1_user_2")
    matcher = SimpleNamespace(state={})

    async def invoke_preprocessor() -> None:
        await prompts._invalidate_prompt_on_command(matcher, event)

    asyncio.run(invoke_preprocessor())

    manager.invalidate.assert_not_called()
    manager.invalidate_event_conversations.assert_not_called()
