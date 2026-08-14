# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.plugins.operations import update_confirmation
from ironsbot.plugins.operations.update_confirmation import UpdateConfirmation
from tests.helpers.onebot_events import private_message_event

if TYPE_CHECKING:
    from nonebot.matcher import Matcher


@pytest.mark.asyncio
async def test_update_confirmation_runs_executor_only_after_affirmative_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies: list[str] = []
    executions: list[str] = []

    async def finish(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    async def execute(_matcher: object, _event: object, _state: object) -> str:
        executions.append("ran")
        return "更新已启动。"

    monkeypatch.setattr(update_confirmation, "finish_event_reply", finish)
    matcher = cast("Matcher", object())

    await update_confirmation._handle_update_confirmation(
        matcher,
        private_message_event("y"),
        {},
        executor=execute,
    )

    assert executions == ["ran"]
    assert replies == ["更新已启动。"]


@pytest.mark.asyncio
async def test_update_confirmation_cancels_without_running_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replies: list[str] = []

    async def finish(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    async def execute(_matcher: object, _event: object, _state: object) -> str:
        pytest.fail("取消不应执行更新")

    monkeypatch.setattr(update_confirmation, "finish_event_reply", finish)
    matcher = cast("Matcher", object())

    await update_confirmation._handle_update_confirmation(
        matcher,
        private_message_event("n"),
        {},
        executor=execute,
    )

    assert replies == ["已取消更新。"]


@pytest.mark.asyncio
async def test_update_confirmation_registers_existing_yes_no_input_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def enter(_matcher: object, _event: object, **kwargs: object) -> None:
        captured.update(kwargs)

    async def execute(_matcher: object, _event: object, _state: object) -> str:
        return "更新已启动。"

    monkeypatch.setattr(update_confirmation, "enter_event_reply_conversation", enter)
    matcher = cast("Matcher", object())
    await update_confirmation.request_update_confirmation(
        matcher,
        private_message_event("/更新数据"),
        UpdateConfirmation(
            namespace="test_update",
            check_message="检查完成。",
            action_label="更新数据",
            executor=execute,
        ),
    )

    reply_check = captured["reply_check"]
    assert captured["namespace"] == "test_update"
    assert callable(reply_check)
    assert reply_check(private_message_event("是")) is True
    assert reply_check(private_message_event("n")) is True
    assert reply_check(private_message_event("稍后")) is False
    assert "回复“是”或“y”确认" in str(captured["prompt"])
