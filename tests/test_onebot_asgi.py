from __future__ import annotations

import asyncio
import hmac
import json
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from ironsbot.app.host import application_lifespan
from ironsbot.app.lifecycle import ApplicationLifecycle
from ironsbot.config.models.transport import OneBotConfig
from ironsbot.integrations.onebot.asgi import OneBotASGI
from ironsbot.integrations.onebot.connections import OneBotConnections
from ironsbot.integrations.onebot.transport import OneBotTransport
from tests.test_onebot_native_reverse import Socket

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.connections import OneBotConnection


@pytest.fixture
def host() -> tuple[FastAPI, OneBotTransport, asyncio.Event, list[dict[str, Any]]]:
    lifecycle = ApplicationLifecycle()
    delivered = asyncio.Event()
    payloads: list[dict[str, Any]] = []

    async def receive(connection: OneBotConnection, payload: dict[str, Any]) -> None:
        assert connection.self_id == "1"
        payloads.append(payload)
        delivered.set()

    transport = OneBotTransport(
        config=OneBotConfig(http_secret="test-secret"),
        access_token="test-token",
        spawn=lifecycle.task_owner.create,
        received=receive,
        notices=receive,
        request_http=AsyncMock(),
        connections=OneBotConnections(),
        observer=lifecycle,
    )
    lifecycle.resource_startup_hooks = (("onebot", transport.start),)
    lifecycle.shutdown_hooks = (("onebot", transport.close),)
    app = FastAPI(lifespan=partial(application_lifespan, lifecycle))
    OneBotASGI(transport).install(app)
    return app, transport, delivered, payloads


@pytest.mark.parametrize(
    "path", ["/onebot/v11/", "/onebot/v11/http", "/onebot/v11/http/"]
)
@pytest.mark.asyncio
async def test_http_routes_verify_signature_over_original_bytes(
    host: tuple[FastAPI, OneBotTransport, asyncio.Event, list[dict[str, Any]]],
    path: str,
) -> None:
    app, transport, delivered, payloads = host
    payload = {"self_id": 1, "post_type": "message", "raw_message": "\u5173\u4e8e"}
    body = json.dumps(payload, ensure_ascii=False).encode()
    signature = "sha1=" + hmac.new(b"test-secret", body, "sha1").hexdigest()
    headers = {"X-Self-ID": "1", "X-Signature": signature}
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app), base_url="http://test") as client,
    ):
        invalid = await client.post(path, content=body + b" ", headers=headers)
        assert invalid.status_code == HTTPStatus.FORBIDDEN
        assert not delivered.is_set()
        valid = await client.post(path, content=body, headers=headers)
        assert valid.status_code == HTTPStatus.NO_CONTENT
        await asyncio.wait_for(delivered.wait(), timeout=2)
        assert payloads == [payload]
    assert transport.accounts.snapshot() == ()
    assert not transport.tasks


@pytest.mark.parametrize("path", ["/onebot/v11/", "/onebot/v11/ws", "/onebot/v11/ws/"])
@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.asyncio
async def test_websocket_routes_accept_text_and_binary_frames(
    host: tuple[FastAPI, OneBotTransport, asyncio.Event, list[dict[str, Any]]],
    path: str,
    *,
    binary: bool,
) -> None:
    app, transport, delivered, payloads = host
    payload = {"self_id": 1, "post_type": "notice", "notice_type": "test"}
    socket = Socket()
    socket.scope["path"] = path
    async with app.router.lifespan_context(app):
        serving = asyncio.create_task(
            app(socket.scope, socket._receive_message, socket._send_message)
        )
        try:
            await asyncio.wait_for(socket.accepted.wait(), timeout=2)
            frame = json.dumps(payload)
            await socket.incoming.put(frame.encode() if binary else frame)
            await asyncio.wait_for(delivered.wait(), timeout=2)
            assert payloads == [payload]
        finally:
            await socket.incoming.put(WebSocketDisconnect(1000))
            await asyncio.wait_for(serving, timeout=2)
    assert transport.accounts.snapshot() == ()
    assert not transport.tasks


@pytest.mark.asyncio
async def test_websocket_rejection_does_not_dispatch_or_publish_connection(
    host: tuple[FastAPI, OneBotTransport, asyncio.Event, list[dict[str, Any]]],
) -> None:
    app, transport, delivered, _payloads = host
    socket = Socket(token="Bearer wrong-token")
    async with app.router.lifespan_context(app):
        await app(socket.scope, socket._receive_message, socket._send_message)
        assert socket.close_calls[0][0] == 1008  # noqa: PLR2004 - WS policy violation
        assert not socket.accepted.is_set()
        assert not delivered.is_set()
        assert transport.accounts.snapshot() == ()
