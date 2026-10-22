# SPDX-License-Identifier: MIT
"""Opt-in own-account commands at the OneBot transport boundary."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

import httpx
from nonebot.adapters.onebot.v11 import (
    Adapter,
    Bot,
)
from nonebot.drivers import URL, HTTPClientMixin, Request, Response
from nonebot.exception import WebSocketClosed

from ironsbot.integrations.onebot.errors import OneBotTransportError
from ironsbot.integrations.onebot.forward_client import OneBotForwardClient
from ironsbot.integrations.onebot.http_api import (
    OneBotHttpApi,
    OneBotHttpRequest,
    OneBotHttpResponse,
)
from ironsbot.integrations.onebot.http_receiver import OneBotHttpReceiver
from ironsbot.integrations.onebot.reverse_server import OneBotReverseServer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Coroutine, Mapping

    from nonebot.drivers import Driver, WebSocket

    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.integrations.onebot.connections import (
        OneBotConnection,
        OneBotEventHandler,
    )
    from ironsbot.integrations.onebot.socket_events import OneBotSocket
    from ironsbot.integrations.onebot.websocket_session import OneBotWebSocketSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _NativeSocket:
    websocket: WebSocket

    @property
    def headers(self) -> Mapping[str, str]:
        return self.websocket.request.headers

    async def accept(self) -> None:
        await self.websocket.accept()

    async def receive(self) -> str | bytes:
        try:
            return await self.websocket.receive()
        except WebSocketClosed:
            raise ConnectionError from None

    async def send(self, text: str) -> None:
        try:
            await self.websocket.send(text)
        except WebSocketClosed:
            raise ConnectionError from None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await self.websocket.close(code, reason)


class SelfCommandAdapter(Adapter):
    def __init__(
        self,
        driver: Driver,
        *,
        spawn: TaskSpawner,
        received: OneBotEventHandler,
        notices: OneBotEventHandler,
        **kwargs: Any,
    ) -> None:
        super().__init__(driver, **kwargs)
        self._spawn = spawn
        self.received = received
        self.notices = notices
        self._socket_bots: dict[OneBotWebSocketSession, Bot] = {}
        self._socket_sessions: WeakKeyDictionary[Bot, OneBotWebSocketSession] = (
            WeakKeyDictionary()
        )
        self.reverse_server = OneBotReverseServer(
            access_token=self.onebot_config.onebot_access_token,
            api_timeout=self.config.api_timeout,
            spawn=self._spawn_event,
            connected=lambda account: account in self.bots,
            on_connect=self._connect_socket,
            on_disconnect=self._disconnect_socket,
            on_event=lambda session, payload: self._dispatch_payload(
                self._socket_bots[session], payload
            ),
        )
        self.http_receiver = OneBotHttpReceiver(
            secret=self.onebot_config.onebot_secret,
            spawn=self._spawn_event,
            connection=self._http_connection,
            on_event=self._dispatch_payload,
        )
        self.forward_clients: list[OneBotForwardClient] = []
        self.http_api = OneBotHttpApi(
            api_roots={
                account: str(url)
                for account, url in self.onebot_config.onebot_api_roots.items()
            },
            access_token=self.onebot_config.onebot_access_token,
            timeout=self.config.api_timeout,
            request=self._request_http,
        )

    def _spawn_event(
        self, coroutine: Coroutine[Any, Any, Any], *, name: str
    ) -> asyncio.Task[Any]:
        task = self._spawn(coroutine, name=name)
        task.add_done_callback(self.tasks.discard)
        self.tasks.add(task)
        return task

    def _connect_socket(self, session: OneBotWebSocketSession) -> None:
        bot = Bot(self, session.self_id)
        self.bot_connect(bot)
        self._socket_bots[session] = bot
        self._socket_sessions[bot] = session

    def _disconnect_socket(self, session: OneBotWebSocketSession) -> None:
        if bot := self._socket_bots.pop(session, None):
            self.bot_disconnect(bot)

    def _http_connection(self, account: str) -> OneBotConnection:
        if (bot := self.bots.get(account)) is None:
            bot = Bot(self, account)
            self.bot_connect(bot)
        return bot

    async def _dispatch_payload(
        self, connection: OneBotConnection, payload: dict[str, Any]
    ) -> None:
        if payload.get("post_type") in ("message", "message_sent"):
            await self.received(connection, payload)
            return
        if payload.get("post_type") == "notice":
            await self.notices(connection, payload)
            return

    async def _handle_http(self, request: Request) -> Response:
        result = self.http_receiver.receive(request.headers, request.content)
        return Response(result.status, content=result.content)

    async def _handle_ws(self, websocket: WebSocket) -> None:
        await self.reverse_server.handle(_NativeSocket(websocket))

    @asynccontextmanager
    async def _open_forward(self, url: URL) -> AsyncIterator[OneBotSocket]:
        headers = {}
        if token := self.onebot_config.onebot_access_token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request("GET", url, headers=headers, timeout=30.0)
        async with self.websocket(request) as socket:
            yield _NativeSocket(socket)

    async def _start_forward(self) -> None:
        if self.forward_clients:
            return
        for url in self.onebot_config.onebot_ws_urls:
            client = OneBotForwardClient(
                connect=partial(self._open_forward, URL(str(url))),
                api_timeout=self.config.api_timeout,
                spawn=self._spawn_event,
                connected=lambda account: account in self.bots,
                on_connect=self._connect_socket,
                on_disconnect=self._disconnect_socket,
                on_event=lambda session, payload: self._dispatch_payload(
                    self._socket_bots[session], payload
                ),
            )
            coroutine = client.run()
            try:
                self._spawn_event(coroutine, name="onebot.forward")
            except BaseException:
                coroutine.close()
                raise
            self.forward_clients.append(client)

    async def _stop(self) -> None:
        self.http_receiver.close()
        self.http_api.close()
        for client in self.forward_clients:
            await client.close()
        await self.reverse_server.close()
        await super()._stop()

    async def _call_api(self, bot: Bot, api: str, **data: Any) -> Any:
        if session := self._socket_sessions.get(bot):
            return await session.call_api(api, **data)
        return await self.http_api.call(bot.self_id, api, **data)

    async def _request_http(self, request: OneBotHttpRequest) -> OneBotHttpResponse:
        if not isinstance(self.driver, HTTPClientMixin):
            raise OneBotTransportError(definitely_not_sent=True) from None
        try:
            response = await self.driver.request(
                Request(
                    "POST",
                    request.url,
                    headers=dict(request.headers),
                    timeout=request.timeout,
                    content=request.body,
                )
            )
        except (httpx.RequestError, OSError, asyncio.TimeoutError):
            raise OneBotTransportError from None
        return OneBotHttpResponse(response.status_code, response.content)
