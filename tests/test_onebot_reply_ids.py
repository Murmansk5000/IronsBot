from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.outbound import (
    BinaryImagePart,
    DeliveryFailureKind,
    OutboundMessage,
    TextPart,
)
from ironsbot.integrations.onebot.message_rendering import (
    OneBotOutboundMessageError,
    render_onebot_outbound_message,
)
from ironsbot.integrations.onebot.receipts import onebot_result_message_id
from ironsbot.integrations.onebot.replies import (
    build_event_reply_message,
    send_portable_event_reply,
)
from tests.helpers.onebot_events import group_message_event


@pytest.mark.parametrize("message_id", [-2147483648, -1, 0, 2147483647])
@pytest.mark.parametrize("command", ["help", "1"])
@pytest.mark.parametrize("image_only", [False, True])
@pytest.mark.asyncio
async def test_native_and_portable_replies_accept_signed_message_ids(
    message_id: int, command: str, *, image_only: bool
) -> None:
    event = group_message_event(command, message_id=message_id)
    matcher = Mock()
    matcher.send = AsyncMock(return_value={"message_id": -42})
    outbound = OutboundMessage(
        (BinaryImagePart(b"png", "image/png"),)
        if image_only
        else (TextPart("progress or result"),)
    )
    native = build_event_reply_message(
        event,
        Message(MessageSegment.image("base64://cG5n"))
        if image_only
        else "progress or result",
    )
    result = await send_portable_event_reply(matcher, event, outbound)

    assert result.delivered
    assert result.message_id == "-42"
    assert native[0] == MessageSegment.reply(message_id)
    assert matcher.send.call_args is not None
    assert str(matcher.send.call_args.args[0]) == str(native)


@pytest.mark.parametrize(
    "value", ["", "-", "+1", "1.0", " 1", "1 ", "1_000", "--1", "abc", "１２"]
)
def test_reply_message_ids_reject_non_decimal_syntax(value: str) -> None:
    with pytest.raises(OneBotOutboundMessageError):
        render_onebot_outbound_message(
            OutboundMessage((TextPart("result"),)), reply_to_id=value
        )


@pytest.mark.parametrize(
    "value", [True, False, [], {}, 1.5, "abc", "1.0", "+1", " 1", "1 ", "１２", None]
)
def test_send_receipt_requires_a_protocol_message_id(value: object) -> None:
    assert onebot_result_message_id({"message_id": value}) is None


@pytest.mark.parametrize("value", [-42, 0, 42, "-42", "0", "42"])
def test_send_receipt_accepts_signed_integer_ids(value: int | str) -> None:
    assert onebot_result_message_id({"message_id": value}) == str(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False, [], {}, 1.5, "abc", None])
async def test_passive_reply_with_malformed_id_is_uncertain_not_success(
    value: object,
) -> None:
    matcher = Mock(send=AsyncMock(return_value={"message_id": value}))
    result = await send_portable_event_reply(
        matcher, group_message_event("help"), OutboundMessage.from_text("result")
    )
    assert not result.delivered
    assert result.failure_kind is DeliveryFailureKind.UNCERTAIN
    matcher.send.assert_awaited_once()
