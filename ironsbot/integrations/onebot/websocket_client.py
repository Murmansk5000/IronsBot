# SPDX-License-Identifier: MIT
"""Forward WebSocket I/O, without a framework driver or reconnect policy."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from websockets.asyncio.client import ClientConnection


@dataclass(frozen=True, slots=True)
class OneBotClientSocket:
    connection: ClientConnection

    async def receive(self) -> str | bytes:
        try:
            return await self.connection.recv()
        except ConnectionClosed:
            raise ConnectionError from None

    async def send(self, text: str) -> None:
        try:
            await self.connection.send(text)
        except ConnectionClosed:
            raise ConnectionError from None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await self.connection.close(code, reason)


@asynccontextmanager
async def open_onebot_socket(
    url: str, *, access_token: str | None
) -> AsyncIterator[OneBotClientSocket]:
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    async with connect(
        url, additional_headers=headers, open_timeout=30.0, close_timeout=30.0
    ) as connection:
        yield OneBotClientSocket(connection)
