# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import cast

import pytest

from ironsbot.integrations.onebot import confirmation
from tests.helpers.onebot_events import private_message_event


@pytest.mark.asyncio
async def test_confirmation_executes_only_after_affirmative_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies: list[str] = []
    executions: list[str] = []

    async def finish(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    async def execute(_matcher: object, _event: object, _state: object) -> str:
        executions.append("ran")
        return "更新已启动。"

    monkeypatch.setattr(confirmation, "finish_event_reply", finish)
    await confirmation._handle_event_confirmation(
        cast("object", object()),
        private_message_event("y"),
        {},
        executor=execute,
    )

    assert executions == ["ran"]
    assert replies == ["更新已启动。"]


@pytest.mark.asyncio
async def test_confirmation_cancels_without_running_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies: list[str] = []

    async def finish(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    async def execute(_matcher: object, _event: object, _state: object) -> str:
        pytest.fail("取消不应执行更新")

    monkeypatch.setattr(confirmation, "finish_event_reply", finish)
    await confirmation._handle_event_confirmation(
        cast("object", object()),
        private_message_event("n"),
        {},
        executor=execute,
    )

    assert replies == ["已取消。"]
