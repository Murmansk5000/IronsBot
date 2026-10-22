from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from ironsbot.integrations.onebot.message_envelope import (
    OneBotMessageEnvelope,
    decode_received_message,
)
from tests.helpers.onebot_events import group_message_event, private_message_event

if TYPE_CHECKING:
    from types import SimpleNamespace

    from pytest import LogCaptureFixture

    from ironsbot.core.message_input import MessageInputContext

pytest_plugins = ("tests.test_shared_onebot_ingress",)

_USER_ID = 101
_GROUP_ID = 456
_MESSAGE_ID = -12


async def _receive_context(
    runtime: SimpleNamespace, payload: dict[str, Any]
) -> MessageInputContext:
    admission = Mock(decide=AsyncMock(side_effect=runtime.admission.decide))
    receiver = replace(runtime.received, admission=admission)
    await receiver.handle(runtime.bot, payload)
    context = admission.decide.call_args.args[0].context
    assert context is not None
    return context


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("message_id", [-12, 0, 42])
async def test_valid_messages_preserve_source_metadata_and_custom_extensions(
    runtime: SimpleNamespace, message_id: int, *, private: bool
) -> None:
    payload = (
        private_message_event("执行", user_id=101, message_id=message_id)
        if private
        else group_message_event("执行", user_id=101, message_id=message_id)
    ).model_dump()
    payload["provider_extension"] = {"nested": [1, 2]}
    before = json.dumps(payload)
    envelope = OneBotMessageEnvelope.model_validate(payload)
    assert envelope.message_id == message_id
    assert envelope.user_id == _USER_ID
    assert envelope.model_dump()["provider_extension"] == {"nested": [1, 2]}
    assert json.dumps(payload) == before
    context = await _receive_context(runtime, payload)
    assert context.message.message_id == str(message_id)
    assert context.message.conversation.kind == ("private" if private else "group")


@pytest.mark.parametrize(
    "field",
    [
        "time",
        "self_id",
        "user_id",
        "message_id",
        "message_type",
        "sub_type",
        "raw_message",
        "font",
        "sender",
        "group_id",
    ],
)
def test_missing_message_fields_are_rejected_without_native_payload_logging(
    caplog: LogCaptureFixture,
    field: str,
) -> None:
    payload = group_message_event("private-marker").model_dump()
    payload.pop(field)
    assert decode_received_message(payload) is None
    assert "invalid message envelope" in caplog.text
    assert "private-marker" not in caplog.text


@pytest.mark.parametrize(
    "field", ["time", "self_id", "user_id", "message_id", "font", "group_id"]
)
def test_boolean_is_not_a_protocol_integer(field: str) -> None:
    payload = group_message_event().model_dump()
    payload[field] = True
    with pytest.raises(ValidationError):
        OneBotMessageEnvelope.model_validate(payload)
    assert decode_received_message(payload) is None


@pytest.mark.parametrize("field", ["nickname", "card", "role", "user_id"])
def test_malformed_sender_is_rejected_without_leaking_values(
    caplog: LogCaptureFixture,
    field: str,
) -> None:
    payload = group_message_event().model_dump()
    payload["sender"][field] = {"secret": "private-marker"}
    assert decode_received_message(payload) is None
    assert "private-marker" not in caplog.text


def test_integer_strings_remain_supported_without_boolean_coercion() -> None:
    payload = group_message_event(message_id=-12).model_dump()
    for field in ("time", "self_id", "user_id", "message_id", "font", "group_id"):
        payload[field] = str(payload[field])
    message = OneBotMessageEnvelope.model_validate(payload)
    assert message.message_id == _MESSAGE_ID
    assert message.group_id == _GROUP_ID


@pytest.mark.asyncio
async def test_reply_envelope_accepts_wire_text_without_importing_quoted_targets(
    runtime: SimpleNamespace,
) -> None:
    payload = group_message_event(
        "执行",
        reply_message_id=-42,
        reply_sender_user_id=333,
    ).model_dump()
    payload["reply"]["message"] = "[CQ:at,qq=777]quoted"
    envelope = OneBotMessageEnvelope.model_validate(payload)
    assert envelope.reply is not None
    assert envelope.reply.message[0]["type"] == "at"
    context = await _receive_context(runtime, payload)
    assert not context.member_mentions
    assert context.message.reply_to_id == "-42"


@pytest.mark.asyncio
async def test_temporary_private_source_group_is_metadata_not_conversation_or_role(
    runtime: SimpleNamespace,
) -> None:
    payload = private_message_event(
        "执行",
        user_id=101,
        sender={"role": "owner"},
    ).model_dump()
    payload.update(group_id=456, sub_type="group")
    envelope = OneBotMessageEnvelope.model_validate(payload)
    assert envelope.group_id == _GROUP_ID
    context = await _receive_context(runtime, payload)
    assert context.message.conversation.kind == "private"
    assert context.message.conversation.id == "101"
    assert context.message.group_role is None
    assert not context.mentions_bot


def test_message_envelope_validation_runs_without_nonebot() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.modules['nonebot'] = None
from ironsbot.integrations.onebot.message_envelope import OneBotMessageEnvelope
message = OneBotMessageEnvelope.model_validate(dict(
    time=0, self_id=1, post_type='message', message_type='group',
    sub_type='normal', user_id=101, message_id=-12,
    message=[dict(type='text', data=dict(text='help'))],
    raw_message='help', font=0, sender=dict(user_id=101), group_id=456,
))
assert message.message_id == -12
assert message.message[0]['data']['text'] == 'help'
""",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
