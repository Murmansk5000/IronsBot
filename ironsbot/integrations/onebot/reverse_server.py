# SPDX-License-Identifier: MIT
"""Application-owned OneBot reverse reception, independent of its ASGI host."""

from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Protocol

from ironsbot.integrations.onebot.socket_events import OneBotSocket, OneBotSocketEvents
from ironsbot.integrations.onebot.websocket_session import OneBotWebSocketSession

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping
    from typing import Any

    from ironsbot.core.tasks import TaskSpawner

logger = logging.getLogger(__name__)


class OneBotReverseSocket(OneBotSocket, Protocol):
    @property
    def headers(self) -> Mapping[str, str]: ...

    async def accept(self) -> None: ...


class OneBotReverseServer:
    def __init__(  # noqa: PLR0913 - explicit transport and lifecycle ports
        self,
        *,
        access_token: str | None,
        api_timeout: float | None,
        spawn: TaskSpawner,
        connected: Callable[[str], bool],
        on_connect: Callable[[OneBotWebSocketSession], None],
        on_disconnect: Callable[[OneBotWebSocketSession], None],
        on_event: Callable[
            [OneBotWebSocketSession, dict[str, Any]], Coroutine[Any, Any, None]
        ],
    ) -> None:
        self.access_token = access_token
        self.api_timeout = api_timeout
        self.connected = connected
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.events = OneBotSocketEvents(spawn, on_event)
        self.sessions: dict[str, OneBotWebSocketSession] = {}
        self._sockets: dict[str, OneBotReverseSocket] = {}
        self._closing = False

    def _authorized_account(self, websocket: OneBotReverseSocket) -> str | None:
        account_id = websocket.headers.get("x-self-id", "")
        scheme, _, supplied = websocket.headers.get("authorization", "").partition(" ")
        authorized = not self.access_token or (
            scheme.casefold() == "bearer"
            and hmac.compare_digest(supplied.encode(), self.access_token.encode())
        )
        if not account_id.isascii() or not account_id.isdecimal() or not authorized:
            return None
        return account_id

    async def _admit_socket(self, websocket: OneBotReverseSocket) -> str | None:
        if self._closing:
            await websocket.close(1001, "OneBot receiver stopping")
            return None
        account_id = self._authorized_account(websocket)
        if account_id is None:
            await websocket.close(1008, "Invalid OneBot connection")
            return None
        if account_id in self.sessions or self.connected(account_id):
            await websocket.close(1008, "Duplicate OneBot connection")
            return None
        return account_id

    async def handle(self, websocket: OneBotReverseSocket) -> None:
        account_id = await self._admit_socket(websocket)
        if account_id is None:
            return
        session = OneBotWebSocketSession(
            account_id, websocket.send, timeout=self.api_timeout
        )
        # Reserve before accept so concurrent handshakes cannot both win.
        self.sessions[account_id] = session
        self._sockets[account_id] = websocket
        connected = False
        try:
            await websocket.accept()
            if self._closing:
                return
            self.on_connect(session)
            connected = True
            await self.events.receive(
                websocket, session, stopping=lambda: self._closing
            )
        except ConnectionError:
            pass
        except Exception as error:  # noqa: BLE001 - never log protocol payloads
            logger.warning(
                "OneBot reverse connection stopped: error_type=%s", type(error).__name__
            )
        finally:
            session.close()
            if self.sessions.get(account_id) is session:
                del self.sessions[account_id]
                self._sockets.pop(account_id, None)
            try:
                if connected:
                    self.on_disconnect(session)
            finally:
                with suppress(Exception):
                    await websocket.close()

    async def close(self) -> None:
        self._closing = True
        for session in self.sessions.values():
            session.close()
        await asyncio.gather(
            *(socket.close() for socket in tuple(self._sockets.values())),
            return_exceptions=True,
        )
