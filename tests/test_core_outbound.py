from __future__ import annotations

import pytest

from ironsbot.core.outbound import (
    BinaryImagePart,
    OutboundMessage,
    RemoteImagePart,
    ReplyContext,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import ConversationRef, Platform

PART_COUNT = 3


def test_outbound_message_accepts_text_and_image_parts() -> None:
    message = OutboundMessage(
        (
            TextPart("hello"),
            BinaryImagePart(b"png", "image/png", "card.png"),
            RemoteImagePart("https://example.test/card.png"),
        )
    )

    assert len(message.parts) == PART_COUNT


def test_outbound_message_rejects_empty_parts() -> None:
    with pytest.raises(ValueError, match="at least one part"):
        OutboundMessage(())


def test_reply_context_and_send_result_require_complete_delivery_state() -> None:
    context = ReplyContext(
        ConversationRef(Platform.ONEBOT, "private", "123"),
        "message-1",
    )

    assert context.message_id == "message-1"
    assert SendResult(delivered=True, message_id="message-2").delivered
    assert not SendResult(delivered=False, error_code="unsupported").delivered


def test_send_result_rejects_incomplete_state() -> None:
    with pytest.raises(ValueError):
        SendResult(delivered=True)
    with pytest.raises(ValueError):
        SendResult(delivered=False)
