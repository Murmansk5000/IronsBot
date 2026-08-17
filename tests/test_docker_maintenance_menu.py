# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.plugins.operations.status import handlers
from tests.helpers.onebot_events import private_message_event

if TYPE_CHECKING:
    from nonebot.matcher import Matcher


class _DockerServiceStub:
    def __init__(self) -> None:
        self.prepared: list[str] = []
        self.executed: list[str] = []
        self.checks = 0

    async def check_image_update(self) -> str:
        self.checks += 1
        return "检测到新镜像。"

    async def prepare_restart_only(self) -> tuple[str, str]:
        self.prepared.append("restart_only")
        return "仅重启。", "process"

    async def prepare_update_and_restart(self) -> tuple[str, str]:
        self.prepared.append("update_and_restart")
        return "更新并重启。", "none"

    async def execute_restart(self, action: str) -> None:
        self.executed.append(action)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("choice", "expected_prepared", "expected_action", "expected_reply"),
    (
        ("1", "restart_only", "process", "仅重启。"),
        ("2", "update_and_restart", "none", "更新并重启。"),
    ),
)
async def test_docker_maintenance_choice_executes_exact_selected_action(
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
    expected_prepared: str,
    expected_action: str,
    expected_reply: str,
) -> None:
    replies: list[str] = []

    async def send(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    monkeypatch.setattr(handlers, "send_event_reply", send)
    service = _DockerServiceStub()

    await handlers._handle_docker_maintenance_action(
        cast("Matcher", object()),
        private_message_event(choice),
        docker_service=service,  # type: ignore[arg-type]
    )

    assert service.prepared == [expected_prepared]
    assert service.executed == [expected_action]
    assert replies == [expected_reply]


@pytest.mark.asyncio
async def test_docker_maintenance_menu_uses_shared_prompt_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def enter(_matcher: object, _event: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(handlers, "enter_event_reply_conversation", enter)
    service = _DockerServiceStub()

    await handlers._open_docker_maintenance_menu(
        cast("Matcher", object()),
        private_message_event("/更新镜像"),
        docker_service=service,  # type: ignore[arg-type]
    )

    reply_check = captured["reply_check"]
    assert captured["namespace"] == handlers.DOCKER_MAINTENANCE_NAMESPACE
    assert captured["prompt"] == handlers.DOCKER_MAINTENANCE_MENU
    assert service.checks == 0
    assert callable(reply_check)
    assert reply_check(private_message_event("1")) is True
    assert reply_check(private_message_event("2")) is True
    assert reply_check(private_message_event("0")) is True
    assert reply_check(private_message_event("y")) is False
    assert len(cast("list[object]", captured["handlers"])) == 1


@pytest.mark.asyncio
async def test_docker_update_command_checks_image_before_showing_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def enter(_matcher: object, _event: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(handlers, "enter_event_reply_conversation", enter)
    service = _DockerServiceStub()

    await handlers._open_docker_maintenance_menu(
        cast("Matcher", object()),
        private_message_event("/更新镜像"),
        docker_service=service,  # type: ignore[arg-type]
        check_image=True,
    )

    assert service.checks == 1
    assert captured["prompt"] == (
        "检测到新镜像。\n\n" + handlers.DOCKER_MAINTENANCE_MENU
    )
