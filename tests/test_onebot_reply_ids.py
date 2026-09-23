from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.integrations.onebot.message_rendering import (
    OneBotOutboundMessageError,
    render_onebot_outbound_message,
)
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
