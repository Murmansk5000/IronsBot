from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ironsbot.core.messaging import AiIntentAction
from ironsbot.plugins.ai import team_actions
from tests.helpers.onebot_events import group_message_event


@pytest.mark.asyncio
async def test_team_recommend_sends_configured_messages_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send_sequence = AsyncMock()
    monkeypatch.setattr(team_actions, "finish_message_sequence", send_sequence)
    matcher = object()
    event = group_message_event("我要加战队")
    action = AiIntentAction(
        action="team_recommend",
        messages=[
            "审核群链接：https://example.com/join",
            "审核群号：123456789",
            "入群后请发送米米号供管理员审核。",
        ],
    )

    await team_actions.run_team_action(
        matcher,  # type: ignore[arg-type]
        event,
        action,
        object(),  # type: ignore[arg-type]
    )

    send_sequence.assert_awaited_once_with(
        matcher,
        [
            "审核群链接：https://example.com/join",
            "审核群号：123456789",
            "入群后请发送米米号供管理员审核。",
        ],
        event=event,
    )
