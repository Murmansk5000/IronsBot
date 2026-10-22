from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from typing import Any

import pytest

from ironsbot.integrations.onebot.errors import OneBotActionError, OneBotTransportError
from ironsbot.integrations.onebot.websocket_session import OneBotWebSocketSession

_SECOND_RESULT = 2
_CONCURRENT_REQUESTS = 2


class Wire:
    def __init__(self) -> None:
        self.sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def send(self, text: str) -> None:
        await self.sent.put(json.loads(text))


@pytest.mark.asyncio
async def test_concurrent_replies_are_scoped_and_can_arrive_out_of_order() -> None:
    wire = Wire()
    session = OneBotWebSocketSession("1", wire.send, timeout=1)
    first = asyncio.create_task(session.call_api("get_login_info"))
    second = asyncio.create_task(session.call_api("send_group_msg", group_id=456))
    a, b = await wire.sent.get(), await wire.sent.get()
    assert a["echo"] != b["echo"]
    assert b["params"] == {"group_id": 456}
    session.receive({"echo": b["echo"], "status": "ok", "retcode": 0, "data": 2})
    session.receive({"echo": a["echo"], "status": "ok", "retcode": 0, "data": 1})
    assert await first == 1
    assert await second == _SECOND_RESULT
    assert session.pending_count == 0


@pytest.mark.asyncio
async def test_another_connection_cannot_consume_reply_and_late_echo_is_ignored() -> (
    None
):
    wire, other_wire = Wire(), Wire()
    session = OneBotWebSocketSession("1", wire.send, timeout=1)
    other = OneBotWebSocketSession("1", other_wire.send, timeout=1)
    waiting = asyncio.create_task(session.call_api("get_login_info"))
    sent = await wire.sent.get()
    response = {"echo": sent["echo"], "status": "ok", "retcode": 0, "data": 1}
    assert other.receive(response)
    assert not waiting.done()
    assert not session.receive({**response, "post_type": "message"})
    assert session.receive(response)
    assert await waiting == 1
    assert session.receive(response)
    assert session.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["timeout", "cancel", "disconnect"])
async def test_pending_requests_are_released_without_retry(outcome: str) -> None:
    wire = Wire()
    session = OneBotWebSocketSession("1", wire.send, timeout=1)
    request = asyncio.create_task(session.call_api("send_group_msg", _timeout=0.02))
    sent = await wire.sent.get()
    assert "_timeout" not in sent["params"]
    if outcome == "cancel":
        request.cancel()
        error_type = asyncio.CancelledError
    elif outcome == "disconnect":
        session.close()
        error_type = OneBotTransportError
    else:
        error_type = TimeoutError
    with pytest.raises(error_type) as caught:
        await request
    if isinstance(caught.value, OneBotTransportError):
        assert not caught.value.definitely_not_sent
    assert session.pending_count == 0
    assert wire.sent.empty()
    assert session.receive({"echo": sent["echo"], "status": "ok", "retcode": 0})


@pytest.mark.asyncio
async def test_disconnect_distinguishes_submitted_and_queued_requests() -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(_text: str) -> None:
        entered.set()
        await release.wait()

    session = OneBotWebSocketSession("1", send, timeout=1)
    submitted = asyncio.create_task(session.call_api("send_group_msg"))
    await entered.wait()
    queued = asyncio.create_task(session.call_api("send_private_msg"))
    await asyncio.sleep(0)
    assert session.pending_count == _CONCURRENT_REQUESTS
    session.close()
    session.close()
    release.set()
    results = await asyncio.gather(submitted, queued, return_exceptions=True)
    assert all(isinstance(item, OneBotTransportError) for item in results)
    assert isinstance(results[0], OneBotTransportError)
    assert isinstance(results[1], OneBotTransportError)
    assert not results[0].definitely_not_sent
    assert results[1].definitely_not_sent
    assert session.pending_count == 0
    with pytest.raises(OneBotTransportError) as caught:
        await session.call_api("send_group_msg")
    assert caught.value.definitely_not_sent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"status": "failed", "retcode": 1200, "wording": "private-detail"},
        {"status": "ok", "retcode": True},
        {"status": "ok", "retcode": "0"},
        {"status": "unknown", "retcode": 0},
        {},
    ],
)
async def test_invalid_or_failed_receipt_never_becomes_success(
    response: dict[str, object],
) -> None:
    wire = Wire()
    session = OneBotWebSocketSession("1", wire.send, timeout=1)
    request = asyncio.create_task(session.call_api("send_group_msg"))
    sent = await wire.sent.get()
    session.receive({**response, "echo": sent["echo"]})
    with pytest.raises(OneBotActionError) as caught:
        await request
    assert "private-detail" not in str(caught.value)
    assert session.pending_count == 0


@pytest.mark.asyncio
async def test_async_ack_has_no_fabricated_delivery_receipt() -> None:
    wire = Wire()
    session = OneBotWebSocketSession("1", wire.send, timeout=1)
    request = asyncio.create_task(session.call_api("send_group_msg_async"))
    sent = await wire.sent.get()
    session.receive(
        {
            "echo": sent["echo"],
            "status": "async",
            "retcode": 1,
            "data": {"message_id": 42},
        }
    )
    assert await request is None


@pytest.mark.asyncio
async def test_serialization_failure_does_not_leave_a_waiter() -> None:
    wire = Wire()
    session = OneBotWebSocketSession("1", wire.send, timeout=1)
    with pytest.raises(TypeError):
        await session.call_api("send_group_msg", message=object())
    assert session.pending_count == 0
    assert wire.sent.empty()


def test_session_can_execute_without_importing_nonebot() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys, asyncio, json
sys.modules['nonebot'] = None
from ironsbot.integrations.onebot.websocket_session import OneBotWebSocketSession
async def run():
    async def send(text):
        payload = json.loads(text)
        session.receive(dict(echo=payload['echo'], status='ok', retcode=0, data=42))
    session = OneBotWebSocketSession('1', send, timeout=1)
    assert await session.call_api('get_login_info') == 42
    assert session.pending_count == 0
asyncio.run(run())
""",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_wire_send_failure_closes_session_and_does_not_retry() -> None:
    calls = 0

    async def send(_text: str) -> None:
        nonlocal calls
        calls += 1
        raise ConnectionError

    session = OneBotWebSocketSession("1", send, timeout=1)
    with pytest.raises(ConnectionError):
        await session.call_api("send_group_msg")
    assert session.pending_count == 0
    with pytest.raises(OneBotTransportError) as caught:
        await session.call_api("send_group_msg")
    assert caught.value.definitely_not_sent
    assert calls == 1
