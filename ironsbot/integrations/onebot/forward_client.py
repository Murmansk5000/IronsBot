# SPDX-License-Identifier: MIT
"""Application-owned forward OneBot connection and reconnect lifecycle."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ironsbot.integrations.onebot.socket_events import (
    OneBotSocketEvents,
    decode_socket_frame,
)
from ironsbot.integrations.onebot.websocket_session import OneBotWebSocketSession
from ironsbot.integrations.onebot.wire_fields import (
    OneBotInteger,  # noqa: TC001 - Pydantic field resolution
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.integrations.onebot.socket_events import OneBotSocket

logger = logging.getLogger(__name__)


class _ConnectEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: OneBotInteger
    self_id: OneBotInteger
    post_type: Literal["meta_event"]
    meta_event_type: Literal["lifecycle"]
    sub_type: Literal["connect"]


class OneBotForwardClient:
    def __init__(  # noqa: PLR0913 - explicit transport and lifecycle ports
        self,
        *,
        connect: Callable[[], AbstractAsyncContextManager[OneBotSocket]],
        api_timeout: float | None,
        spawn: TaskSpawner,
        connected: Callable[[str], bool],
        on_connect: Callable[[OneBotWebSocketSession], None],
        on_disconnect: Callable[[OneBotWebSocketSession], None],
        on_event: Callable[
            [OneBotWebSocketSession, dict[str, Any]], Coroutine[Any, Any, None]
        ],
        reconnect_seconds: float = 3.0,
    ) -> None:
        self.connect = connect
        self.api_timeout = api_timeout
        self.connected = connected
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.events = OneBotSocketEvents(spawn, on_event)
        self.reconnect_seconds = reconnect_seconds
        self.session: OneBotWebSocketSession | None = None
        self._socket: OneBotSocket | None = None
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        while not self._stopping.is_set():
            try:
                async with self.connect() as socket:
                    self._socket = socket
                    try:
                        await self._serve(socket)
                    finally:
                        self._socket = None
            except Exception as error:  # noqa: BLE001 - no URL or provider payloads
                logger.warning(
                    "OneBot forward connection stopped: error_type=%s",
                    type(error).__name__,
                )
            if not self._stopping.is_set():
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self.reconnect_seconds
                    )

    async def _handshake(self, socket: OneBotSocket) -> _ConnectEvent | None:
        while not self._stopping.is_set():
            payload = decode_socket_frame(await socket.receive())
            try:
                return _ConnectEvent.model_validate(payload)
            except ValidationError:
                continue
        return None

    async def _serve(self, socket: OneBotSocket) -> None:
        registered = False
        session = None
        try:
            event = await self._handshake(socket)
            if event is None or self._stopping.is_set():
                return
            account = str(event.self_id)
            if self.connected(account):
                logger.warning("OneBot forward connection rejected: duplicate account")
                return
            session = OneBotWebSocketSession(
                account, socket.send, timeout=self.api_timeout
            )
            self.session = session
            self.on_connect(session)
            registered = True
            await self.events.receive(socket, session, stopping=self._stopping.is_set)
        finally:
            if session is not None:
                session.close()
            self.session = None
            try:
                if registered:
                    assert session is not None
                    self.on_disconnect(session)
            finally:
                with suppress(Exception):
                    await socket.close()

    async def close(self) -> None:
        self._stopping.set()
        if self.session is not None:
            self.session.close()
        if self._socket is not None:
            with suppress(Exception):
                await self._socket.close()
