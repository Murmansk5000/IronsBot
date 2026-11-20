from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.diagnostic_context import diagnostic_operation
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.message_origin import message_origin
from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.command_errors import CommandErrorReporter
from ironsbot.services.error_diagnostics import DiagnosticFormatter, ErrorDiagnostic
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.seer.render_coordinator import RenderCoordinator
from ironsbot.services.seer.render_pipeline import (
    RenderRequest,
    mark_render_step,
    render_step,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any


def context(platform: Platform, *, private: bool = False) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "A" * 32, account_id="app"),
            ConversationRef(
                platform, "private" if private else "group", "B" * 32, account_id="app"
            ),
            "original-event",
            "do-not-disclose-chat-body",
        ),
        mentions_bot=True,
        execution_identity=ExecutionIdentity(platform, "app", "测试机器人"),
        actor_display_name="测试成员",
    )


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("private", [False, True])
def test_diagnostic_snapshot_masks_content_and_has_local_source(
    platform: Platform, *, private: bool
) -> None:
    source = context(platform, private=private)
    with (
        message_origin(source),
        diagnostic_operation(
            "seer.pet",
            "4911技能 token=private-secret https://media.example/a?sign=secret",
        ),
    ):
        event = ErrorDiagnostic.current("资料查询", "prepare")
        background = ErrorDiagnostic.background("B站投递", "send", task="动态123")
    text = DiagnosticFormatter().format("TimeoutError", event)
    for secret in (
        "private-secret",
        "https://",
        source.message.text,
        "A" * 32,
        "B" * 32,
    ):
        assert secret not in text
    assert "测试机器人" in text and "测试成员" in text
    assert "错误编号：" in text and "原消息摘要：" in text
    assert ("4911技能" in text) is (not private)
    assert background.origin is None
    assert "触发消息：不适用" in DiagnosticFormatter().describe(background)


def test_trusted_official_mapping_does_not_require_network() -> None:
    source = context(Platform.QQ_OFFICIAL)
    principals = IdentityPrincipalService()
    principals.register_configured_group(
        alias="fictional",
        onebot_group_id="123456",
        official_endpoints=[("app", "B" * 32)],
    )
    principals.register_configured_actor(
        alias="member", onebot_qq_id="234567", official_endpoints=[("app", "A" * 32)]
    )
    formatter = DiagnosticFormatter(principals, {"123456": "测试群"})
    text = formatter.describe(ErrorDiagnostic("资料", "render", source))
    assert "测试群（群号：123456）" in text and "用户号：234567" in text
    assert "B" * 32 not in text and "A" * 32 not in text


@pytest.mark.asyncio
async def test_notices_are_isolated_and_repeat_summary_keeps_error_id() -> None:
    notices = AsyncMock()
    tasks: list[asyncio.Task[None]] = []
    finish_window = asyncio.Event()

    async def wait_window(_seconds: float) -> None:
        await finish_window.wait()

    def spawn(work: Coroutine[Any, Any, None]) -> None:
        tasks.append(asyncio.create_task(work))

    reporter = CommandErrorReporter(notices, spawn=spawn, sleep=wait_window)
    source = context(Platform.QQ_OFFICIAL)
    await reporter.report(source, RuntimeError())
    await reporter.report(source, RuntimeError())
    other = replace(
        source,
        message=replace(
            source.message,
            conversation=replace(source.message.conversation, id="C" * 32),
        ),
    )
    await reporter.report(other, RuntimeError())
    other_bot = replace(
        source, execution_identity=ExecutionIdentity(Platform.QQ_OFFICIAL, "another")
    )
    await reporter.report(other_bot, RuntimeError())
    assert notices.send.await_count == len(("first", "other-group", "other-bot"))
    finish_window.set()
    await asyncio.gather(*tasks)
    texts = [call.args[0] for call in notices.send.await_args_list]
    assert any("同类错误汇总：2次" in text for text in texts)
    first_id = texts[0].split("错误编号：", 1)[1].splitlines()[0]
    assert first_id in texts[-1]


@pytest.mark.asyncio
async def test_render_timeout_keeps_original_step_location_and_budget() -> None:
    timeout = 0.01
    coordinator = RenderCoordinator(AsyncMock(), timeout)

    async def prepare() -> bytes:
        mark_render_step("素材请求 pet_head/4911")
        await asyncio.sleep(1)
        return b"unused"

    result = await coordinator.execute(RenderRequest("pet_info"), prepare)
    assert result.status == "failed" and result.failure_stage == "prepare"
    assert result.failure_step == "素材请求 pet_head/4911"
    assert "prepare" in result.failure_location
    assert result.timeout_seconds == timeout and result.elapsed_seconds is not None


@pytest.mark.asyncio
async def test_input_without_message_does_not_borrow_an_unrelated_message() -> None:
    notices = AsyncMock()
    reporter = CommandErrorReporter(notices)
    source = context(Platform.QQ_OFFICIAL)
    with message_origin(source):
        await reporter.report(command_context_from_input(source), RuntimeError())
    text = notices.send.call_args.args[0]
    assert "入口未提供" in text
    assert "后台任务" not in text
    assert "原消息摘要" not in text and "4911技能" not in text


@pytest.mark.asyncio
async def test_render_step_survives_timeout_cancellation() -> None:
    coordinator = RenderCoordinator(AsyncMock(), 0.01)

    async def prepare() -> bytes:
        with render_step("素材请求 pet_head/4911"):
            await asyncio.sleep(1)
        return b"unused"

    result = await coordinator.execute(RenderRequest("pet_info"), prepare)
    assert result.failure_step == "素材请求 pet_head/4911"


def test_background_targets_keep_stable_labels_and_platform_trace() -> None:
    source = context(Platform.QQ_OFFICIAL)
    event = ErrorDiagnostic.background(
        "B站投递", "send", targets=(source.message.conversation,)
    )
    event = replace(event, trace_id="f" * 32)
    text = DiagnosticFormatter().format("上传失败", event)
    assert "任务目标：qq_official/group 未解析（摘要：" in text
    assert "B" * 32 not in text and "Trace ID：" + "f" * 32 in text
