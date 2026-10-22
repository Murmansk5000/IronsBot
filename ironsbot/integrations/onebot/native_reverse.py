# SPDX-License-Identifier: MIT
"""Native event bridge for the application-owned reverse WebSocket sessions."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from contextlib import suppress
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from nonebot.adapters.onebot.v11 import Bot
from nonebot.exception import WebSocketClosed

from ironsbot.integrations.onebot.websocket_session import OneBotWebSocketSession

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Adapter
    from nonebot.drivers import WebSocket

    from ironsbot.core.tasks import TaskSpawner

logger = logging.getLogger(__name__)


class NativeOneBotReverseServer:
    def __init__(self, adapter: Adapter, spawn: TaskSpawner) -> None:
        self.adapter = adapter
        self.spawn = spawn
        self.sessions: dict[str, OneBotWebSocketSession] = {}
        self._by_bot: WeakKeyDictionary[Bot, OneBotWebSocketSession] = (
            WeakKeyDictionary()
        )
        self._sockets: dict[str, WebSocket] = {}
        self._closing = False

    def session_for(self, bot: Bot) -> OneBotWebSocketSession | None:
        return self._by_bot.get(bot)

    def _authorized_account(self, websocket: WebSocket) -> str | None:
        headers = websocket.request.headers
        account_id = headers.get("x-self-id", "")
        authorization = headers.get("authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        expected = self.adapter.onebot_config.onebot_access_token
        authorized = not expected or (
            scheme.casefold() == "bearer"
            and hmac.compare_digest(supplied.encode(), expected.encode())
        )
        if not account_id.isascii() or not account_id.isdecimal() or not authorized:
            return None
        return account_id

    async def _admit_socket(self, websocket: WebSocket) -> str | None:
        if self._closing:
            await websocket.close(1001, "OneBot receiver stopping")
            return None
        account_id = self._authorized_account(websocket)
        if account_id is None:
            await websocket.close(1008, "Invalid OneBot connection")
            return None
        # Reserve before awaiting accept, so parallel handshakes cannot both win.
        if account_id in self.adapter.bots or account_id in self.sessions:
            await websocket.close(1008, "Duplicate OneBot connection")
            return None
        return account_id

    async def handle(self, websocket: WebSocket) -> None:
        account_id = await self._admit_socket(websocket)
        if account_id is None:
            return

        async def send(payload: str) -> None:
            try:
                await websocket.send(payload)
            except WebSocketClosed:
                raise ConnectionError from None

        session = OneBotWebSocketSession(
            account_id, send, timeout=self.adapter.config.api_timeout
        )
        self.sessions[account_id] = session
        bot = Bot(self.adapter, account_id)
        self._by_bot[bot] = session
        self._sockets[account_id] = websocket
        connected = False
        try:
            await websocket.accept()
            if self._closing:
                return
            self.adapter.bot_connect(bot)
            connected = True
            await self._receive(websocket, bot, session)
        except WebSocketClosed:
            pass
        except Exception as error:  # noqa: BLE001 - protocol boundary, never log payloads
            logger.warning(
                "OneBot reverse connection stopped: error_type=%s",
                type(error).__name__,
            )
        finally:
            session.close()
            if self.sessions.get(account_id) is session:
                del self.sessions[account_id]
                self._sockets.pop(account_id, None)
            if connected:
                self.adapter.bot_disconnect(bot)
            with suppress(Exception):
                await websocket.close()

    async def _receive(
        self, websocket: WebSocket, bot: Bot, session: OneBotWebSocketSession
    ) -> None:
        while not self._closing:
            raw = await websocket.receive()
            if self._closing:
                return
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                message = "OneBot frame must be an object"
                raise TypeError(message)
            if session.receive(payload):
                continue
            if str(payload.get("self_id", "")) != session.self_id:
                message = "OneBot frame does not match connection"
                raise ValueError(message)
            if event := self.adapter.json_to_event(payload):
                task = self.spawn(bot.handle_event(event), name="onebot.native.event")
                task.add_done_callback(self.adapter.tasks.discard)
                self.adapter.tasks.add(task)

    async def close(self) -> None:
        self._closing = True
        for session in self.sessions.values():
            session.close()
        await asyncio.gather(
            *(socket.close() for socket in tuple(self._sockets.values())),
            return_exceptions=True,
        )
