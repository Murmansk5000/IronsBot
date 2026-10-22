from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize("token", ["", "socket-test-token"])
@pytest.mark.parametrize("binary", [False, True])
def test_real_forward_socket_shares_protocol_without_framework(
    token: str, *, binary: bool
) -> None:
    script = r"""
import sys
sys.modules["nonebot"] = None
import asyncio
import json
from functools import partial
from websockets.asyncio.server import serve
from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.onebot.forward_client import OneBotForwardClient
from ironsbot.integrations.onebot.websocket_client import open_onebot_socket

token = sys.argv[1] or None
binary = sys.argv[2] == "True"

async def run():
    owner = TaskOwner()
    handled, closed = asyncio.Event(), asyncio.Event()
    connected, disconnected = [], []
    seen_headers, actions = [], []
    async def server_peer(ws):
        seen_headers.append(ws.request.headers.get("Authorization"))
        for payload in (
            dict(time=0, self_id=1, post_type="meta_event",
                 meta_event_type="lifecycle", sub_type="connect"),
            dict(self_id=1, post_type="notice"),
        ):
            frame = json.dumps(payload)
            await ws.send(frame.encode() if binary else frame)
        action = json.loads(await ws.recv())
        actions.append(action)
        await ws.send(json.dumps(dict(echo=action["echo"], status="ok",
                                      retcode=0, data={"message_id": 42})))
        await ws.wait_closed()
        closed.set()

    async def event(session, payload):
        assert session.self_id == "1" and payload["post_type"] == "notice"
        assert await session.call_api("send_group_msg", group_id=2) == {"message_id":42}
        handled.set()

    async with serve(server_peer, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = OneBotForwardClient(
            connect=partial(open_onebot_socket, f"ws://127.0.0.1:{port}",
                            access_token=token),
            api_timeout=1, spawn=owner.create, connected=lambda _: False,
            on_connect=connected.append, on_disconnect=disconnected.append,
            on_event=event,
        )
        running = owner.create(client.run(), name="onebot.forward")
        try:
            await asyncio.wait_for(handled.wait(), timeout=3)
        finally:
            await client.close()
            await asyncio.wait_for(running, timeout=3)
            await owner.cancel_all()
        await asyncio.wait_for(closed.wait(), timeout=3)
    assert seen_headers == [f"Bearer {token}" if token else None]
    assert len(connected) == len(disconnected) == 1
    assert connected[0] is disconnected[0]
    assert connected[0].pending_count == 0 and not owner.tasks
    assert actions[0]["action"] == "send_group_msg"
    assert actions[0]["params"] == {"group_id":2}
    assert not any(name.startswith("nonebot.") for name in sys.modules)

asyncio.run(run())
print("REAL_FORWARD_OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, token, str(binary)],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "REAL_FORWARD_OK"


@pytest.mark.parametrize("cancel", [False, True])
def test_real_socket_closure_and_cancellation_release_connection(
    *, cancel: bool
) -> None:
    script = r"""
import sys
sys.modules["nonebot"] = None
import asyncio
from websockets.asyncio.server import serve
from ironsbot.integrations.onebot.websocket_client import open_onebot_socket

async def run():
    closed, ready = asyncio.Event(), asyncio.Event()
    cancel = sys.argv[1] == "True"
    async def peer(ws):
        if not cancel:
            await ws.close(1008, "private-close-reason")
        await ws.wait_closed()
        closed.set()
    async with serve(peer, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async def receive():
            async with open_onebot_socket(f"ws://127.0.0.1:{port}",
                                          access_token=None) as wire:
                ready.set()
                if cancel:
                    await wire.receive()
                else:
                    for call in (wire.receive, lambda: wire.send("after-close")):
                        try:
                            await call()
                        except ConnectionError as error:
                            assert str(error) == ""
                        else:
                            raise AssertionError("closed socket accepted I/O")
        task = asyncio.create_task(receive())
        await asyncio.wait_for(ready.wait(), timeout=3)
        if cancel:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("cancellation was swallowed")
        else:
            await asyncio.wait_for(task, timeout=3)
        await asyncio.wait_for(closed.wait(), timeout=3)
    assert not any(name.startswith("nonebot.") for name in sys.modules)

asyncio.run(run())
print("SOCKET_RELEASED")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(cancel)],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "SOCKET_RELEASED"
