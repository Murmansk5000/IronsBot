from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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
from tests.helpers.onebot_events import group_message_event
from tests.helpers.onebot_inputs import message_input_context

if TYPE_CHECKING:
    from types import SimpleNamespace

pytest_plugins = ("tests.test_shared_onebot_ingress",)


@pytest.mark.parametrize("message_id", [-2147483648, -1, 0, 2147483647])
@pytest.mark.parametrize("command", ["help", "1"])
@pytest.mark.parametrize("image_only", [False, True])
@pytest.mark.asyncio
async def test_actual_outbound_replies_accept_signed_message_ids(
    runtime: SimpleNamespace, message_id: int, command: str, *, image_only: bool
) -> None:
    event = group_message_event(command, message_id=message_id)
    runtime.transport.response = {"message_id": -42}
    outbound = OutboundMessage(
        (BinaryImagePart(b"png", "image/png"),)
        if image_only
        else (TextPart("progress or result"),)
    )
    result = await runtime.messenger.reply_from(
        runtime.bot, message_input_context(event), outbound
    )

    assert result.delivered
    assert result.message_id == "-42"
    (sent,) = runtime.sends
    message = sent["message"]
    assert message[0] == {"type": "reply", "data": {"id": str(message_id)}}
    assert [part["type"] for part in message] == (
        ["reply", "image"] if image_only else ["reply", "at", "text", "text"]
    )
    if image_only:
        assert message[-1]["data"]["file"] == "base64://cG5n"
    else:
        assert message[-1]["data"] == {"text": "progress or result"}


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
    runtime: SimpleNamespace,
    value: object,
) -> None:
    runtime.transport.response = {"message_id": value}
    result = await runtime.messenger.reply_from(
        runtime.bot,
        message_input_context(group_message_event("help")),
        OutboundMessage.from_text("result"),
    )
    assert not result.delivered
    assert result.failure_kind is DeliveryFailureKind.UNCERTAIN
    assert len(runtime.sends) == 1
