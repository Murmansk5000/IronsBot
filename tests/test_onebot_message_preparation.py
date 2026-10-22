from __future__ import annotations

import asyncio
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from ironsbot.integrations.onebot.message_preparation import prepare_onebot_message
from ironsbot.integrations.onebot.message_segments import decode_onebot_segments
from tests.helpers.onebot_events import group_message_event, private_message_event

if TYPE_CHECKING:
    from pytest import LogCaptureFixture

    from ironsbot.integrations.onebot.message_segments import OneBotMessage

_INPUTS = {
    "plain": "执行",
    "empty": "",
    "leading": "[CQ:at,qq=1]  执行",
    "two_leading": "[CQ:at,qq=1] [CQ:at,qq=1] 执行",
    "three_leading": "[CQ:at,qq=1] [CQ:at,qq=1] [CQ:at,qq=1] 执行",
    "member_first": "[CQ:at,qq=333][CQ:at,qq=1]执行",
    "only_bot": "[CQ:at,qq=1]",
    "tail": "执行[CQ:at,qq=1]",
    "tail_spaces": "执行[CQ:at,qq=1]   ",
    "addressed_tail": "执行[CQ:at,qq=1]   ",
    "nickname": "demo， 执行",
    "nickname_prefix": "demography",
    "nickname_case": "DEMO 执行",
    "reply_bot": "[CQ:reply,id=-12][CQ:at,qq=1]  执行",
    "reply_member": "[CQ:reply,id=-12][CQ:at,qq=333]  执行",
    "reply_unknown_sender": "[CQ:reply,id=-12]  执行",
    "reply_last": "执行[CQ:reply,id=-12]",
    "reply_failure": "[CQ:reply,id=-12][CQ:at,qq=1]执行",
    "reply_malformed": "[CQ:reply,id=-12]执行",
    "reply_bad_id": "[CQ:reply,id=invalid]执行",
    "adjacent": "执行",
}


def _reply(sender: int | None = 1) -> dict[str, object]:
    return {
        "time": 0,
        "message_type": "group",
        "message_id": -12,
        "real_id": -12,
        "sender": {"user_id": sender},
        "message": "[CQ:at,qq=777]quoted-body",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list(_INPUTS))
@pytest.mark.parametrize("private", [False, True])
async def test_preparation_preserves_installed_sdk_protocol_behavior(
    monkeypatch: pytest.MonkeyPatch, mode: str, *, private: bool
) -> None:
    parts: OneBotMessage = decode_onebot_segments(_INPUTS[mode])
    if mode == "adjacent":
        parts = [
            {"type": "text", "data": {"text": "demo "}},
            {"type": "text", "data": {"text": "执行"}},
        ]
    source = deepcopy(parts)
    sender = (
        None
        if mode == "reply_unknown_sender"
        else (333 if mode == "reply_member" else 1)
    )
    response = {} if mode == "reply_malformed" else _reply(sender)
    failure = RuntimeError("private-marker") if mode == "reply_failure" else None
    connection = Mock(
        self_id="1", call_api=AsyncMock(return_value=response, side_effect=failure)
    )
    prepared = await prepare_onebot_message(
        connection,
        parts,
        private=private,
        addressed_to_bot=mode == "addressed_tail",
        nicknames={"demo"},
    )
    get_msg = AsyncMock(return_value=response, side_effect=failure)
    native = cast(
        "Bot",
        SimpleNamespace(
            self_id="1",
            config=SimpleNamespace(nickname={"demo"}),
            get_msg=get_msg,
        ),
    )
    event = private_message_event() if private else group_message_event()
    event.message = Message(
        MessageSegment(part["type"], part["data"]) for part in deepcopy(parts)
    )
    event.to_me = mode == "addressed_tail"
    dispatched = AsyncMock()
    monkeypatch.setattr("nonebot.adapters.onebot.v11.bot.handle_event", dispatched)
    await Bot.handle_event(native, event)
    dispatched.assert_awaited_once_with(native, event)
    assert prepared.message == [
        {"type": part.type, "data": part.data} for part in event.message
    ]
    assert prepared.addressed_to_bot == event.to_me
    assert (prepared.reply.model_dump() if prepared.reply else None) == (
        event.reply.model_dump() if event.reply else None
    )
    assert parts == source
    assert connection.call_api.await_count == get_msg.await_count


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("private-marker"), None])
async def test_bad_reply_logs_no_response_or_exception_body(
    caplog: LogCaptureFixture, failure: Exception | None
) -> None:
    connection = Mock(
        self_id="1",
        call_api=AsyncMock(
            return_value={"secret": "private-marker"}, side_effect=failure
        ),
    )
    result = await prepare_onebot_message(
        connection, decode_onebot_segments("[CQ:reply,id=-12]执行"), private=False
    )
    assert result.reply is None
    assert "metadata unavailable" in caplog.text
    assert "private-marker" not in caplog.text


@pytest.mark.asyncio
async def test_cancelled_reply_lookup_does_not_continue_to_command_preparation() -> (
    None
):
    connection = Mock(
        self_id="1", call_api=AsyncMock(side_effect=asyncio.CancelledError)
    )
    parts = decode_onebot_segments("[CQ:reply,id=-12]demo 执行")
    source = deepcopy(parts)
    with pytest.raises(asyncio.CancelledError):
        await prepare_onebot_message(
            connection, parts, private=False, nicknames={"demo"}
        )
    assert parts == source
    connection.call_api.assert_awaited_once_with("get_msg", message_id=-12)


def test_protocol_preparation_runs_without_nonebot() -> None:
    script = """
import sys
sys.modules['nonebot'] = None
import asyncio
from ironsbot.integrations.onebot.message_preparation import prepare_onebot_message
from ironsbot.integrations.onebot.message_segments import decode_onebot_segments
async def run():
    class Connection:
        self_id = '1'
        async def call_api(self, api, **params):
            assert api == 'get_msg' and params == {'message_id':-12}
            return dict(time=0, message_type='group', message_id=-12, real_id=-12,
                sender={'user_id':1}, message='[CQ:at,qq=777]quoted')
    parts = decode_onebot_segments('[CQ:reply,id=-12][CQ:at,qq=1]demo 执行')
    prepared = await prepare_onebot_message(
        Connection(), parts, private=False, nicknames={'demo'},
    )
    assert prepared.addressed_to_bot
    assert prepared.message == [{'type':'text', 'data':{'text':'执行'}}]
    assert parts[0]['type'] == 'reply' and len(parts) == 3
    assert prepared.reply.sender.user_id == 1
asyncio.run(run())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
