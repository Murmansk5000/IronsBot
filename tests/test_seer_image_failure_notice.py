from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.message_origin import current_message_origin, message_origin
from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.seer.image_failure_notice import AdminImageFailureReporter
from ironsbot.services.seer.images import ImageSourceError

if TYPE_CHECKING:
    from ironsbot.services.messaging.admin_notice import AdminNoticeService


@pytest.mark.asyncio
async def test_image_failure_notice_is_restricted_to_admin_delivery() -> None:
    admin_notices = AsyncMock()
    reporter = AdminImageFailureReporter(
        cast("AdminNoticeService", admin_notices),
    )

    await reporter("pet_body", "1400466", ImageSourceError("network detail"))

    admin_notices.send.assert_awaited_once_with(
        "⚠️ 赛尔图片素材获取失败\n"
        "执行机器人：未确定\n"
        "素材类型：pet_body\n"
        "资源标识：1400466\n"
        "异常：ImageSourceError: network detail",
        subscription_key="render_crash_notice",
        action_name="Seer image source failure notice",
    )


@pytest.mark.asyncio
async def test_batch_notice_keeps_original_executor_and_lists_all_failed_assets() -> (
    None
):
    notices = AsyncMock()
    reporter = AdminImageFailureReporter(cast("AdminNoticeService", notices))
    identity = ExecutionIdentity(Platform.ONEBOT, "123456", "执行账号")
    await reporter.report_batch(
        (
            ("pet_head", "4354", ImageSourceError("timeout")),
            ("item", "20", ImageSourceError("unavailable")),
        ),
        identity,
        degraded=True,
    )
    notices.send.assert_awaited_once()
    text = notices.send.await_args.args[0]
    assert "执行账号（QQ：123456）" in text
    assert "pet_head" in text and "item" in text
    assert "本次结果不写入缓存" in text


@pytest.mark.asyncio
async def test_notice_failure_does_not_abort_partial_render() -> None:
    notices = AsyncMock()
    notices.send.side_effect = RuntimeError("notice offline")
    reporter = AdminImageFailureReporter(cast("AdminNoticeService", notices))
    await reporter.report_batch((("pet_head", "1", ImageSourceError("timeout")),))


@pytest.mark.asyncio
async def test_image_notice_includes_triggering_group_and_sender() -> None:
    notices = AsyncMock()
    resolver = AsyncMock(
        return_value="群：测试群（QQ群：456）\n用户：群昵称（QQ：789）"
    )
    reporter = AdminImageFailureReporter(
        cast("AdminNoticeService", notices), origin_resolver=resolver
    )
    group = ConversationRef(Platform.ONEBOT, "group", "456")
    context = MessageInputContext(
        IncomingMessageRef(
            Platform.ONEBOT, ActorRef(Platform.ONEBOT, "789"), group, "1", "query"
        ),
        mentions_bot=True,
    )

    with message_origin(context):
        await reporter.report_batch((("pet_head", "1", ImageSourceError("timeout")),))

    resolver.assert_awaited_once_with(context)
    assert (
        "群：测试群（QQ群：456）\n用户：群昵称（QQ：789）"
        in notices.send.await_args.args[0]
    )
    assert current_message_origin() is None
