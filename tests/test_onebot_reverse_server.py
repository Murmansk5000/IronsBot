from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.onebot.errors import OneBotTransportError
from ironsbot.integrations.onebot.reverse_server import OneBotReverseServer


class Socket:
    def __init__(self) -> None:
        self.headers = {"x-self-id": "1", "authorization": "Bearer test-token"}
        self.accepted = asyncio.Event()
        self.incoming: asyncio.Queue[str | bytes | Exception] = asyncio.Queue()
        self.sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.closed = False

    async def accept(self) -> None:
        self.accepted.set()

    async def receive(self) -> str | bytes:
        value = await self.incoming.get()
        if isinstance(value, Exception):
            raise value
        return value

    async def send(self, text: str) -> None:
        await self.sent.put(json.loads(text))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        del code, reason
        self.closed = True
        await self.incoming.put(ConnectionError())


@pytest.mark.asyncio
@pytest.mark.parametrize("binary", [False, True])
async def test_server_dispatch_and_rpc_use_one_owned_connection(
    *, binary: bool
) -> None:
    owner, socket = TaskOwner(), Socket()
    connected, disconnected = Mock(), Mock()
    handled = AsyncMock()
    server = OneBotReverseServer(
        access_token="test-token",
        api_timeout=1,
        spawn=owner.create,
        connected=lambda _: False,
        on_connect=connected,
        on_disconnect=disconnected,
        on_event=handled,
    )
    serving = asyncio.create_task(server.handle(socket))
    try:
        await socket.accepted.wait()
        session = server.sessions["1"]
        payload = {"self_id": 1, "post_type": "notice", "notice_type": "notify"}
        raw = json.dumps(payload)
        await socket.incoming.put(raw.encode() if binary else raw)
        request = asyncio.create_task(session.call_api("get_login_info"))
        sent = await asyncio.wait_for(socket.sent.get(), timeout=1)
        await socket.incoming.put(
            json.dumps(
                {"echo": sent["echo"], "status": "ok", "retcode": 0, "data": {}}
            )
        )
        assert await request == {}
        await asyncio.gather(*tuple(owner.tasks))
        handled.assert_awaited_once_with(session, payload)
        connected.assert_called_once_with(session)
        assert session.pending_count == 0
    finally:
        await server.close()
        await serving
        await owner.cancel_all()
    disconnected.assert_called_once_with(session)
    assert server.sessions == {}
    assert socket.closed


@pytest.mark.asyncio
async def test_rejected_task_closes_coroutine_and_connection() -> None:
    socket = Socket()
    spawn = Mock(side_effect=RuntimeError("owner stopped"))
    disconnected = Mock()
    server = OneBotReverseServer(
        access_token="test-token",
        api_timeout=1,
        spawn=spawn,
        connected=lambda _: False,
        on_connect=Mock(),
        on_disconnect=disconnected,
        on_event=AsyncMock(),
    )
    await socket.incoming.put('{"self_id":1,"post_type":"message"}')
    await server.handle(socket)
    spawn.assert_called_once()
    coroutine = spawn.call_args.args[0]
    assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED
    disconnected.assert_called_once()
    assert server.sessions == {}
    assert socket.closed


@pytest.mark.asyncio
async def test_failed_disconnect_hook_still_closes_socket() -> None:
    socket = Socket()
    server = OneBotReverseServer(
        access_token="test-token",
        api_timeout=1,
        spawn=TaskOwner().create,
        connected=lambda _: False,
        on_connect=Mock(),
        on_disconnect=Mock(side_effect=RuntimeError("disconnect failed")),
        on_event=AsyncMock(),
    )
    await socket.incoming.put(ConnectionError())
    with pytest.raises(RuntimeError, match="disconnect failed"):
        await server.handle(socket)
    assert server.sessions == {}
    assert socket.closed


@pytest.mark.asyncio
async def test_cancelled_receiver_releases_calls_and_unregisters_connection() -> None:
    socket = Socket()
    disconnected = Mock()
    server = OneBotReverseServer(
        access_token="test-token",
        api_timeout=1,
        spawn=TaskOwner().create,
        connected=lambda _: False,
        on_connect=Mock(),
        on_disconnect=disconnected,
        on_event=AsyncMock(),
    )
    serving = asyncio.create_task(server.handle(socket))
    await socket.accepted.wait()
    session = server.sessions["1"]
    request = asyncio.create_task(session.call_api("get_login_info"))
    await socket.sent.get()
    serving.cancel()
    with pytest.raises(asyncio.CancelledError):
        await serving
    with pytest.raises(OneBotTransportError) as error:
        await request
    assert not error.value.definitely_not_sent
    disconnected.assert_called_once_with(session)
    assert server.sessions == {}
    assert socket.closed


def test_reverse_reception_and_receipts_run_with_framework_imports_blocked() -> None:
    script = """
import sys
sys.modules['nonebot'] = None
import asyncio
import json
from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.onebot.reverse_server import OneBotReverseServer

async def run():
    class Socket:
        headers = {'x-self-id':'1', 'authorization':'Bearer test-token'}
        def __init__(self):
            self.incoming = asyncio.Queue()
            self.accepted = asyncio.Event()
        async def accept(self):
            self.accepted.set()
        async def receive(self):
            item = await self.incoming.get()
            if item is None:
                raise ConnectionError()
            return item
        async def send(self, raw):
            payload = json.loads(raw)
            assert payload['action'] == 'send_private_msg'
            assert payload['params'] == {'user_id':101, 'message':'result'}
            await self.incoming.put(json.dumps(dict(
                echo=payload['echo'], status='ok', retcode=0,
                data={'message_id':-42},
            )))
        async def close(self, code=1000, reason=''):
            await self.incoming.put(None)
    socket, owner = Socket(), TaskOwner()
    received, disconnected = asyncio.Event(), []
    async def dispatch(session, payload):
        assert payload == {'self_id':1, 'post_type':'message'}
        result = await session.call_api(
            'send_private_msg', user_id=101, message='result',
        )
        assert result == {'message_id':-42}
        received.set()
    server = OneBotReverseServer(
        access_token='test-token', api_timeout=1, spawn=owner.create,
        connected=lambda _:False, on_connect=lambda _:None,
        on_disconnect=disconnected.append, on_event=dispatch,
    )
    serving = asyncio.create_task(server.handle(socket))
    await socket.accepted.wait()
    session = server.sessions['1']
    await socket.incoming.put('{"self_id":1,"post_type":"message"}')
    await asyncio.wait_for(received.wait(), timeout=2)
    await server.close()
    await serving
    await owner.cancel_all()
    assert disconnected == [session]
    assert server.sessions == {} and session.pending_count == 0
    assert not any(name.startswith('nonebot.') for name in sys.modules)
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
