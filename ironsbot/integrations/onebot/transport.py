# SPDX-License-Identifier: MIT
"""Own OneBot sessions and publish connection facts to the common lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11.config import Config
from nonebot.drivers import (
    URL,
    ASGIMixin,
    HTTPServerSetup,
    Request,
    Response,
    WebSocketServerSetup,
)
from nonebot.exception import WebSocketClosed

from ironsbot.core.platform import BotAccountRef, Platform
from ironsbot.integrations.onebot.forward_client import OneBotForwardClient
from ironsbot.integrations.onebot.http_api import (
    OneBotHttpApi,
)
from ironsbot.integrations.onebot.http_receiver import OneBotHttpReceiver
from ironsbot.integrations.onebot.reverse_server import OneBotReverseServer
from ironsbot.integrations.onebot.websocket_client import open_onebot_socket

if TYPE_CHECKING:
    from collections.abc import Coroutine, Mapping

    from nonebot.drivers import Driver, WebSocket

    from ironsbot.core.account_lifecycle import BotConnectionObserver
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.integrations.onebot.connections import (
        OneBotConnection,
        OneBotConnections,
        OneBotEventHandler,
    )
    from ironsbot.integrations.onebot.http_api import OneBotHttpExchange


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


@dataclass(frozen=True, slots=True)
class OneBotHttpConnection:
    self_id: str
    api: OneBotHttpApi

    async def call_api(self, api: str, **data: Any) -> object:
        return await self.api.call(self.self_id, api, **data)


class OneBotTransport:
    def _setup(self) -> None:
        if isinstance(self.driver, ASGIMixin):
            for path in ("/onebot/v11/", "/onebot/v11/http", "/onebot/v11/http/"):
                self.driver.setup_http_server(
                    HTTPServerSetup(URL(path), "POST", "OneBot HTTP", self._handle_http)
                )
            for path in ("/onebot/v11/", "/onebot/v11/ws", "/onebot/v11/ws/"):
                self.driver.setup_websocket_server(
                    WebSocketServerSetup(URL(path), "OneBot WS", self._handle_ws)
                )
        if self.onebot_config.onebot_ws_urls:
            self.driver._lifespan.on_ready(self._start_forward)

    def __init__(  # noqa: PLR0913 - explicit I/O, account and lifecycle ports
        self,
        driver: Driver,
        *,
        spawn: TaskSpawner,
        received: OneBotEventHandler,
        notices: OneBotEventHandler,
        request_http: OneBotHttpExchange,
        connections: OneBotConnections,
        observer: BotConnectionObserver,
    ) -> None:
        self.driver = driver
        self.onebot_config = Config.model_validate(driver.config.model_dump())
        self.api_timeout = driver.config.api_timeout
        self.accounts = connections
        self.observer = observer
        self._spawn = spawn
        self.received = received
        self.notices = notices
        self.tasks: set[asyncio.Task[Any]] = set()
        self._closing = False
        self.reverse_server = OneBotReverseServer(
            access_token=self.onebot_config.onebot_access_token,
            api_timeout=self.api_timeout,
            spawn=self._spawn_event,
            connected=lambda account: self.accounts.get(account) is not None,
            on_connect=self._connected,
            on_disconnect=self._disconnected,
            on_event=self._dispatch_payload,
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
            timeout=self.api_timeout,
            request=request_http,
        )
        self._setup()

    def _spawn_event(
        self, coroutine: Coroutine[Any, Any, Any], *, name: str
    ) -> asyncio.Task[Any]:
        task = self._spawn(coroutine, name=name)
        task.add_done_callback(self.tasks.discard)
        self.tasks.add(task)
        return task

    def _connected(self, connection: OneBotConnection) -> None:
        if self._closing:
            raise ConnectionError
        self.accounts.connect(connection)
        coroutine = self.observer.bot_connect(
            BotAccountRef(Platform.ONEBOT, connection.self_id)
        )
        try:
            self._spawn_event(coroutine, name="onebot.connected")
        except BaseException:
            coroutine.close()
            self.accounts.disconnect(connection)
            raise

    def _disconnected(self, connection: OneBotConnection) -> None:
        if self.accounts.disconnect(connection) and not self._closing:
            coroutine = self.observer.bot_disconnect(
                BotAccountRef(Platform.ONEBOT, connection.self_id)
            )
            try:
                self._spawn_event(coroutine, name="onebot.disconnected")
            except BaseException:
                coroutine.close()
                raise

    def _http_connection(self, account: str) -> OneBotConnection:
        if (connection := self.accounts.get(account)) is None:
            connection = OneBotHttpConnection(account, self.http_api)
            self._connected(connection)
        return connection

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

    async def _start_forward(self) -> None:
        if self.forward_clients:
            return
        for url in self.onebot_config.onebot_ws_urls:
            client = OneBotForwardClient(
                connect=partial(
                    open_onebot_socket,
                    str(url),
                    access_token=self.onebot_config.onebot_access_token,
                ),
                api_timeout=self.api_timeout,
                spawn=self._spawn_event,
                connected=lambda account: self.accounts.get(account) is not None,
                on_connect=self._connected,
                on_disconnect=self._disconnected,
                on_event=self._dispatch_payload,
            )
            coroutine = client.run()
            try:
                self._spawn_event(coroutine, name="onebot.forward")
            except BaseException:
                coroutine.close()
                raise
            self.forward_clients.append(client)

    async def close(self) -> None:
        self._closing = True
        connections = self.accounts.snapshot()
        self.http_receiver.close()
        self.http_api.close()
        try:
            try:
                for client in self.forward_clients:
                    await client.close()
            finally:
                await self.reverse_server.close()
        finally:
            for connection in connections:
                self.accounts.disconnect(connection)
            try:
                for connection in connections:
                    await self.observer.bot_disconnect(
                        BotAccountRef(Platform.ONEBOT, connection.self_id)
                    )
            finally:
                tasks = tuple(self.tasks)
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                self.tasks.clear()
