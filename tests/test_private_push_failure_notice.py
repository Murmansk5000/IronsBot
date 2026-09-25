from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.outbound import DeliveryFailureKind, OutboundMessage, SendResult
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.services.messaging.private_push_failure_notice import (
    report_private_push_failures,
)
from ironsbot.services.messaging.proactive_delivery import ProactiveDeliverySummary
from tests.test_proactive_delivery import FakeMessenger, _delivery

if TYPE_CHECKING:
    from ironsbot.services.messaging.admin_notice import AdminNoticeService


@pytest.mark.asyncio
async def test_private_failure_notified_once_after_final_attempt() -> None:
    target = ConversationRef(Platform.ONEBOT, "private", "123456")
    messenger = FakeMessenger(
        scripted_results=[
            SendResult(
                delivered=False,
                error_code="temporary",
                failure_kind=DeliveryFailureKind.RETRYABLE,
            ),
            SendResult(delivered=False, error_code="rejected"),
        ]
    )
    delivery, _, _ = _delivery(messenger=messenger)
    notice = AsyncMock()
    delivery = replace(delivery, private_failure_notice=notice)
    summary = await delivery.send(
        OutboundMessage.from_text("message"), (target,), action_name="daily push"
    )
    assert summary.failed == (target,)
    assert messenger.calls == [
        (target, OutboundMessage.from_text("message")),
        (target, OutboundMessage.from_text("message")),
    ]
    notice.assert_awaited_once_with("daily push", summary)


@pytest.mark.asyncio
async def test_private_failure_notice_identifies_target_and_skips_bilibili() -> None:
    target = ConversationRef(Platform.ONEBOT, "private", "123456")
    receipt = SendResult(delivered=False, error_code="offline", attempted=False)
    summary = ProactiveDeliverySummary((), (target,), (), ((target, receipt),))
    notices = AsyncMock()
    await report_private_push_failures(
        cast("AdminNoticeService", notices), "daily window", summary
    )
    text = notices.send_private_to_superusers.await_args.args[0]
    assert "用户 123456" in text
    assert "未发送" in text
    assert "执行机器人：未确定" in text
    await report_private_push_failures(
        cast("AdminNoticeService", notices), "Bilibili dynamic link push", summary
    )
    notices.send_private_to_superusers.assert_awaited_once()
