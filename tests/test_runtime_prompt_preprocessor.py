import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from ironsbot.runtime import prompts


def test_command_preprocessor_keeps_queued_conversations_open(
    monkeypatch: Any,
) -> None:
    manager = SimpleNamespace(
        invalidate_event_conversations=Mock(),
        invalidate=Mock(),
    )

    monkeypatch.setattr(prompts, "get_prompt_session_manager", lambda _matcher: manager)

    event = SimpleNamespace(get_session_id=lambda: "group_1_user_2")
    matcher = SimpleNamespace(priority=1)
    asyncio.run(prompts._invalidate_prompt_on_command(matcher, event))

    manager.invalidate.assert_called_once_with("group_1_user_2")
    manager.invalidate_event_conversations.assert_not_called()
