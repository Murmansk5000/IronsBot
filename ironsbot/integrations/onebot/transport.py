# SPDX-License-Identifier: MIT
"""Own OneBot sessions and publish connection facts to the common lifecycle."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from ironsbot.core.platform import BotAccountRef, Platform
from ironsbot.integrations.onebot.forward_client import OneBotForwardClient
from ironsbot.integrations.onebot.http_api import (
    OneBotHttpApi,
)
from ironsbot.integrations.onebot.http_receiver import OneBotHttpReceiver
from ironsbot.integrations.onebot.reverse_server import OneBotReverseServer
from ironsbot.integrations.onebot.websocket_client import open_onebot_socket

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from ironsbot.config.models.transport import OneBotConfig
    from ironsbot.core.account_lifecycle import BotConnectionObserver
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.integrations.onebot.connections import (
        OneBotConnection,
        OneBotConnections,
        OneBotEventHandler,
    )
    from ironsbot.integrations.onebot.http_api import OneBotHttpExchange


@dataclass(frozen=True, slots=True)
class OneBotHttpConnection:
    self_id: str
    api: OneBotHttpApi

    async def call_api(self, api: str, **data: Any) -> object:
        return await self.api.call(self.self_id, api, **data)


class OneBotTransport:
    def __init__(  # noqa: PLR0913 - explicit I/O, account and lifecycle ports
        self,
        *,
        config: OneBotConfig,
        access_token: str | None,
        spawn: TaskSpawner,
        received: OneBotEventHandler,
        notices: OneBotEventHandler,
        request_http: OneBotHttpExchange,
        connections: OneBotConnections,
        observer: BotConnectionObserver,
    ) -> None:
        self.config = config
        self.access_token = access_token
        self.accounts = connections
        self.observer = observer
        self._spawn = spawn
        self.received = received
        self.notices = notices
        self.tasks: set[asyncio.Task[Any]] = set()
        self._closing = False
        self.reverse_server = OneBotReverseServer(
            access_token=access_token,
            api_timeout=config.api_timeout,
            spawn=self._spawn_event,
            connected=lambda account: self.accounts.get(account) is not None,
            on_connect=self._connected,
            on_disconnect=self._disconnected,
            on_event=self._dispatch_payload,
        )
        self.http_receiver = OneBotHttpReceiver(
            secret=config.http_secret,
            spawn=self._spawn_event,
            connection=self._http_connection,
            on_event=self._dispatch_payload,
        )
        self.forward_clients: list[OneBotForwardClient] = []
        self.http_api = OneBotHttpApi(
            api_roots={account: str(url) for account, url in config.api_roots.items()},
            access_token=access_token,
            timeout=config.api_timeout,
            request=request_http,
        )

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

    async def start(self) -> None:
        if self._closing:
            msg = "OneBot transport is closed"
            raise RuntimeError(msg)
        if self.forward_clients:
            return
        for url in self.config.ws_urls:
            client = OneBotForwardClient(
                connect=partial(
                    open_onebot_socket,
                    str(url),
                    access_token=self.access_token,
                ),
                api_timeout=self.config.api_timeout,
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
