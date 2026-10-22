from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.adapters.onebot.utils import WSUrl
from nonebot.drivers import URL

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.onebot.errors import OneBotTransportError
from ironsbot.integrations.onebot.forward_client import OneBotForwardClient
from tests.test_onebot_native_reverse import _reverse_message_case
from tests.test_onebot_reverse_server import Socket

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ironsbot.integrations.onebot.self_commands import SelfCommandAdapter

pytest_plugins = ("tests.test_onebot_native_reverse",)


def _connect_event(**fields: object) -> dict[str, Any]:
    return {
        "time": 0,
        "self_id": 1,
        "post_type": "meta_event",
        "meta_event_type": "lifecycle",
        "sub_type": "connect",
        **fields,
    }


@pytest.fixture
def forward() -> SimpleNamespace:
    owner, socket = TaskOwner(), Socket()
    ready, exited = asyncio.Event(), asyncio.Event()
    connected = Mock(side_effect=lambda _: ready.set())
    disconnected = Mock()
    events = AsyncMock()

    @asynccontextmanager
    async def connect() -> AsyncIterator[Socket]:
        try:
            yield socket
        finally:
            exited.set()

    client = OneBotForwardClient(
        connect=connect,
        api_timeout=1,
        spawn=owner.create,
        connected=lambda _: False,
        on_connect=connected,
        on_disconnect=disconnected,
        on_event=events,
    )
    return SimpleNamespace(
        client=client,
        owner=owner,
        socket=socket,
        ready=ready,
        exited=exited,
        connected=connected,
        disconnected=disconnected,
        events=events,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("binary", [False, True])
async def test_forward_waits_for_connect_then_shares_event_and_rpc_path(
    forward: SimpleNamespace,
    *,
    binary: bool,
) -> None:
    serving = asyncio.create_task(forward.client.run())
    # Neither normal events, API echoes nor an incomplete connect can register.
    for payload in (
        {"self_id": 1, "post_type": "message"},
        {"echo": "late"},
        {**_connect_event(), "time": True},
    ):
        await forward.socket.incoming.put(json.dumps(payload))
    assert forward.client.session is None
    raw = json.dumps(_connect_event())
    await forward.socket.incoming.put(raw.encode() if binary else raw)
    await asyncio.wait_for(forward.ready.wait(), timeout=2)
    session = forward.client.session
    assert session is not None
    request = asyncio.create_task(session.call_api("get_login_info"))
    sent = await asyncio.wait_for(forward.socket.sent.get(), timeout=2)
    await forward.socket.incoming.put(
        json.dumps(
            {"echo": sent["echo"], "status": "ok", "retcode": 0, "data": {"user_id": 1}}
        )
    )
    assert await request == {"user_id": 1}
    payload = {"self_id": 1, "post_type": "notice", "notice_type": "notify"}
    await forward.socket.incoming.put(json.dumps(payload))
    await forward.client.close()
    await asyncio.wait_for(serving, timeout=2)
    await asyncio.gather(*tuple(forward.owner.tasks))
    # Closing before the queued notice is read must not dispatch work after stop.
    forward.events.assert_not_awaited()
    assert session.pending_count == 0
    forward.connected.assert_called_once_with(session)
    forward.disconnected.assert_called_once_with(session)
    assert forward.client.session is None and forward.socket.closed


@pytest.mark.asyncio
async def test_forward_cancellation_releases_pending_and_preserves_uncertain_send(
    forward: SimpleNamespace,
) -> None:
    serving = asyncio.create_task(forward.client.run())
    await forward.socket.incoming.put(json.dumps(_connect_event()))
    await asyncio.wait_for(forward.ready.wait(), timeout=2)
    session = forward.client.session
    assert session is not None
    pending = asyncio.create_task(session.call_api("send_group_msg", group_id=456))
    await asyncio.wait_for(forward.socket.sent.get(), timeout=2)
    serving.cancel()
    with pytest.raises(asyncio.CancelledError):
        await serving
    with pytest.raises(OneBotTransportError) as caught:
        await pending
    assert not caught.value.definitely_not_sent
    assert session.pending_count == 0
    with pytest.raises(OneBotTransportError) as stale:
        await session.call_api("send_group_msg", group_id=456)
    assert stale.value.definitely_not_sent
    forward.disconnected.assert_called_once_with(session)
    assert forward.exited.is_set() and forward.socket.closed


@pytest.mark.asyncio
async def test_duplicate_forward_account_is_not_registered(
    forward: SimpleNamespace,
) -> None:
    forward.client.connected = lambda _: True
    await forward.socket.incoming.put(json.dumps(_connect_event()))
    serving = asyncio.create_task(forward.client.run())
    await asyncio.wait_for(forward.exited.wait(), timeout=2)
    await forward.client.close()
    await asyncio.wait_for(serving, timeout=2)
    forward.connected.assert_not_called()
    forward.disconnected.assert_not_called()
    assert forward.client.session is None and forward.socket.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["[]", "not-json", '{"self_id":2,"post_type":"notice"}']
)
async def test_bad_or_foreign_forward_frame_closes_without_payload_logging(
    forward: SimpleNamespace,
    bad: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await forward.socket.incoming.put(json.dumps(_connect_event()))
    await forward.socket.incoming.put(bad)
    forward.disconnected.side_effect = RuntimeError("private-marker")
    serving = asyncio.create_task(forward.client.run())
    await asyncio.wait_for(forward.exited.wait(), timeout=2)
    await forward.client.close()
    await asyncio.wait_for(serving, timeout=2)
    forward.events.assert_not_awaited()
    assert "private-marker" not in caplog.text
    assert forward.socket.closed and forward.client.session is None


@pytest.mark.asyncio
async def test_forward_reconnect_cannot_reuse_old_session_or_receipts(
    forward: SimpleNamespace,
) -> None:
    sockets = [forward.socket, Socket()]
    opened: asyncio.Queue[Socket] = asyncio.Queue()
    calls = iter(sockets)

    @asynccontextmanager
    async def connect() -> AsyncIterator[Socket]:
        socket = next(calls)
        await opened.put(socket)
        yield socket

    forward.client.connect = connect
    forward.client.reconnect_seconds = 0
    serving = asyncio.create_task(forward.client.run())
    first = await asyncio.wait_for(opened.get(), timeout=2)
    await first.incoming.put(json.dumps(_connect_event()))
    await asyncio.wait_for(forward.ready.wait(), timeout=2)
    old = forward.client.session
    assert old is not None
    pending = asyncio.create_task(old.call_api("get_login_info"))
    old_request = await asyncio.wait_for(first.sent.get(), timeout=2)
    await first.incoming.put(ConnectionError())
    second = await asyncio.wait_for(opened.get(), timeout=2)
    with pytest.raises(OneBotTransportError):
        await pending
    forward.ready.clear()
    await second.incoming.put(json.dumps(_connect_event()))
    await asyncio.wait_for(forward.ready.wait(), timeout=2)
    new = forward.client.session
    assert new is not None and new is not old
    with pytest.raises(OneBotTransportError) as closed:
        await old.call_api("send_group_msg")
    assert closed.value.definitely_not_sent
    assert second.sent.empty()
    current = asyncio.create_task(new.call_api("get_login_info"))
    new_request = await asyncio.wait_for(second.sent.get(), timeout=2)
    assert old_request["echo"] != new_request["echo"]
    for request, data in ((old_request, "old"), (new_request, "new")):
        await second.incoming.put(
            json.dumps(
                {
                    "echo": request["echo"],
                    "status": "ok",
                    "retcode": 0,
                    "data": data,
                }
            )
        )
    assert await current == "new"
    forward.events.assert_not_awaited()
    await forward.client.close()
    await asyncio.wait_for(serving, timeout=2)
    assert forward.disconnected.call_count == len(sockets)


@pytest.mark.asyncio
async def test_forward_task_rejection_closes_coroutine_and_socket(
    forward: SimpleNamespace,
) -> None:
    reject = Mock(side_effect=RuntimeError("owner stopped"))
    from ironsbot.integrations.onebot.socket_events import OneBotSocketEvents

    forward.client.events = OneBotSocketEvents(reject, forward.events)
    await forward.socket.incoming.put(json.dumps(_connect_event()))
    await forward.socket.incoming.put('{"self_id":1,"post_type":"notice"}')
    serving = asyncio.create_task(forward.client.run())
    await asyncio.wait_for(forward.exited.wait(), timeout=2)
    await forward.client.close()
    await asyncio.wait_for(serving, timeout=2)
    reject.assert_called_once()
    assert inspect.getcoroutinestate(reject.call_args.args[0]) == inspect.CORO_CLOSED
    assert forward.socket.closed


@pytest.mark.asyncio
async def test_forward_close_while_waiting_for_connect_never_registers(
    forward: SimpleNamespace,
) -> None:
    serving = asyncio.create_task(forward.client.run())
    await asyncio.sleep(0)
    await forward.client.close()
    await asyncio.wait_for(serving, timeout=2)
    forward.connected.assert_not_called()
    forward.disconnected.assert_not_called()
    assert forward.socket.closed and forward.client.session is None


@pytest.mark.asyncio
async def test_forward_close_during_connector_cannot_publish_late_connection(
    forward: SimpleNamespace,
) -> None:
    opening, release = asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def connect() -> AsyncIterator[Socket]:
        opening.set()
        await release.wait()
        yield forward.socket

    forward.client.connect = connect
    serving = asyncio.create_task(forward.client.run())
    await asyncio.wait_for(opening.wait(), timeout=2)
    await forward.client.close()
    await forward.socket.incoming.put(json.dumps(_connect_event()))
    release.set()
    await asyncio.wait_for(serving, timeout=2)
    forward.connected.assert_not_called()
    assert forward.socket.closed and forward.client.session is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source", ["group", "private", "temporary_private", "own_minimal"]
)
@pytest.mark.parametrize("wire_format", ["array", "cq"])
async def test_native_forward_binding_uses_shared_business_and_connection_receipt(  # noqa: PLR0913 - source and wire-format fixture matrix
    runtime: SimpleNamespace,
    adapter: SelfCommandAdapter,
    raw_path: SimpleNamespace,
    source: str,
    wire_format: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, private, own = _reverse_message_case(runtime, adapter, source, wire_format)
    socket = Socket()

    @asynccontextmanager
    async def connect(_url: URL) -> AsyncIterator[Socket]:
        yield socket

    monkeypatch.setattr(adapter, "_open_forward", connect)
    adapter.onebot_config.onebot_ws_urls = {WSUrl("ws://test/onebot")}
    await socket.incoming.put(json.dumps(_connect_event()))
    await socket.incoming.put(json.dumps(payload))
    await adapter._start_forward()
    await adapter._start_forward()
    assert len(adapter.forward_clients) == 1
    try:
        sent = await asyncio.wait_for(socket.sent.get(), timeout=2)
        assert sent["action"] == ("send_private_msg" if private else "send_group_msg")
        assert sent["params"]["user_id" if private else "group_id"] == (
            101 if private else 456
        )
        assert sent["params"]["message"][0]["type"] == "reply"
        assert any(part["type"] == "at" for part in sent["params"]["message"]) is not (
            private or own
        )
        await socket.incoming.put(
            json.dumps(
                {
                    "echo": sent["echo"],
                    "status": "ok",
                    "retcode": 0,
                    "data": {"message_id": 123},
                }
            )
        )
        client = adapter.forward_clients[0]
        # Wait on the actual event tasks, leaving the owned connection runner live.
        events = tuple(
            task for task in adapter.tasks if task.get_name() == "onebot.event"
        )
        await asyncio.wait_for(asyncio.gather(*events), timeout=2)
        runtime.execute.assert_awaited_once()
        assert runtime.sends == []
        assert len(raw_path.contexts) == 1
        raw_path.native_conversion.assert_not_called()
        raw_path.native_dispatch.assert_not_awaited()
        raw_path.sdk_preprocessing.assert_not_awaited()
        runtime.ai.chat_reply.assert_not_awaited()
        assert client.session is not None and client.session.pending_count == 0
    finally:
        await adapter._stop()
    assert adapter.bots == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("same_actor", [False, True])
async def test_multiple_forward_connections_keep_account_and_receipt_ownership(
    runtime: SimpleNamespace,
    adapter: SelfCommandAdapter,
    raw_path: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    same_actor: bool,
) -> None:
    from ironsbot.core.platform import ConversationRef, Platform
    from tests.helpers.onebot_events import group_message_event

    sockets = {"ws://first/": Socket(), "ws://second/": Socket()}
    runtime.policies[ConversationRef(Platform.ONEBOT, "group", "457")] = frozenset(
        {"help"}
    )

    @asynccontextmanager
    async def connect(url: URL) -> AsyncIterator[Socket]:
        yield sockets[str(url)]

    monkeypatch.setattr(adapter, "_open_forward", connect)
    adapter.onebot_config.onebot_ws_urls = {WSUrl(url) for url in sockets}
    for index, socket in enumerate(sockets.values(), start=1):
        await socket.incoming.put(json.dumps(_connect_event(self_id=index)))
        payload = group_message_event(
            "执行",
            user_id=101 if same_actor else 100 + index,
            self_id=index,
            group_id=455 + index,
        ).model_dump()
        payload.pop("original_message", None)
        await socket.incoming.put(json.dumps(payload))
    await adapter._start_forward()
    try:
        echoes = []
        for index, socket in enumerate(sockets.values(), start=1):
            sent = await asyncio.wait_for(socket.sent.get(), timeout=2)
            assert sent["params"]["group_id"] == 455 + index
            echoes.append(sent["echo"])
            await socket.incoming.put(
                json.dumps(
                    {
                        "echo": sent["echo"],
                        "status": "ok",
                        "retcode": 0,
                        "data": {"message_id": 123},
                    }
                )
            )
        assert len(set(echoes)) == len(sockets)
        events = tuple(
            task for task in adapter.tasks if task.get_name() == "onebot.event"
        )
        await asyncio.wait_for(asyncio.gather(*events), timeout=2)
        # Transport isolation must not bypass the existing shared actor cooldown.
        expected = 1 if same_actor else len(sockets)
        assert runtime.execute.await_count == expected
        assert {context.request_bot_id for context in raw_path.contexts} == {"1", "2"}
        assert runtime.sends == []
        raw_path.native_conversion.assert_not_called()
        raw_path.native_dispatch.assert_not_awaited()
    finally:
        await adapter._stop()
    assert adapter.bots == {}


@pytest.mark.asyncio
async def test_forward_opener_uses_existing_token_without_accepting_server_socket(
    adapter: SelfCommandAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = Mock(
        receive=AsyncMock(side_effect=ConnectionError),
        send=AsyncMock(),
        close=AsyncMock(),
        accept=AsyncMock(),
    )
    requests = []

    @asynccontextmanager
    async def connect(request: Any) -> AsyncIterator[Any]:
        requests.append(request)
        yield socket

    monkeypatch.setattr(adapter, "websocket", connect)
    adapter.onebot_config.onebot_access_token = "test-token"
    async with adapter._open_forward(URL("ws://test/onebot")) as wire:
        with pytest.raises(ConnectionError):
            await wire.receive()
    assert requests[0].headers["Authorization"] == "Bearer test-token"
    socket.accept.assert_not_awaited()


def test_forward_lifecycle_is_independent_of_nonebot() -> None:
    script = """
import sys
sys.modules['nonebot'] = None
import asyncio
import json
from contextlib import asynccontextmanager
from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.onebot.forward_client import OneBotForwardClient
async def run():
    owner = TaskOwner()
    ready, handled = asyncio.Event(), asyncio.Event()
    ended = []
    class Socket:
        def __init__(self):
            self.frames = asyncio.Queue()
        async def receive(self):
            frame = await self.frames.get()
            if frame is None:
                raise ConnectionError()
            return frame
        async def send(self, text):
            pass
        async def close(self, code=1000, reason=''):
            await self.frames.put(None)
    socket = Socket()
    @asynccontextmanager
    async def connect():
        yield socket
    async def event(session, payload):
        assert session.self_id == '1' and payload['post_type'] == 'notice'
        handled.set()
    client = OneBotForwardClient(connect=connect, api_timeout=1,
        spawn=owner.create, connected=lambda _: False,
        on_connect=lambda _: ready.set(), on_disconnect=ended.append, on_event=event)
    serving = owner.create(client.run(), name='onebot.forward')
    await socket.frames.put(json.dumps(dict(time=0, self_id=1, post_type='meta_event',
        meta_event_type='lifecycle', sub_type='connect')))
    await asyncio.wait_for(ready.wait(), timeout=2)
    await socket.frames.put('{"self_id":1,"post_type":"notice"}')
    await asyncio.wait_for(handled.wait(), timeout=2)
    await client.close()
    await asyncio.wait_for(serving, timeout=2)
    await owner.cancel_all()
    assert len(ended) == 1 and client.session is None and not owner.tasks
    assert not any(n.startswith('nonebot.') for n in sys.modules)
asyncio.run(run())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
