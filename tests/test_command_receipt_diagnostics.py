from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.command_errors import CommandErrorReporter


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_failed_receipt_is_not_a_fabricated_connection_exception(
    platform: Platform,
) -> None:
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "fictional-user"),
            ConversationRef(platform, "group", "fictional-group"),
            "event",
            "query",
        ),
        mentions_bot=True,
    )
    notices = AsyncMock()
    reporter = CommandErrorReporter(notices)
    result = SendResult(
        delivered=False,
        error_code="upload_confirm:11001",
        error_message="task missing token=private-secret",
        failure_kind=DeliveryFailureKind.PERMANENT,
        http_status=404,
        failure_phase="upload_confirm",
        request_method="POST",
        request_endpoint="/v2/groups/{target}/upload_part_finish",
        trace_id="fictional-trace",
    )
    await reporter.report(context, result, "send")
    text = notices.send.call_args.args[0]
    assert "11001" in text and "404" in text and "task missing" in text
    assert "fictional-trace" in text and "upload_part_finish" in text
    assert "ConnectionError" not in text and "unknown" not in text
    assert "private-secret" not in text
    await reporter.report(context, result, "send")
    notices.send.assert_awaited_once()
