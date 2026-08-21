import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from ironsbot.runtime import prompts
from ironsbot.runtime.matchers import EXPLICIT_COMMAND_STATE_KEY
from ironsbot.runtime.prompt_sessions import PromptSessionManager


def test_explicit_command_preprocessor_closes_queued_conversations(
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

    manager.invalidate.assert_called_once_with("group_1_user_2")
    manager.invalidate_event_conversations.assert_called_once_with(event)


def test_menu_router_preprocessor_keeps_queued_conversations_open(
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


def test_explicit_command_closes_an_active_menu_for_the_same_session(
    monkeypatch: Any,
) -> None:
    manager = PromptSessionManager()
    context = manager.start_queued_conversation(
        namespace="push_subscription",
        event_session_id="group_1_user_2",
        state={},
        reply_check=lambda _event: True,
        handlers=[],
    )
    monkeypatch.setattr(prompts, "get_prompt_session_manager", lambda _matcher: manager)

    event = SimpleNamespace(get_session_id=lambda: "group_1_user_2")
    matcher = SimpleNamespace(state={EXPLICIT_COMMAND_STATE_KEY: True})

    async def invoke_preprocessor() -> None:
        await prompts._invalidate_prompt_on_command(matcher, event)

    asyncio.run(invoke_preprocessor())

    assert not context.active
    assert (
        manager.queued_conversation_for(
            namespace="push_subscription",
            event_session_id="group_1_user_2",
        )
        is None
    )
