# SPDX-License-Identifier: MIT
"""ASGI wire conversion for the application-owned OneBot transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.requests import Request  # noqa: TC002 - FastAPI evaluates annotations.
from starlette.responses import Response
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI

    from ironsbot.integrations.onebot.transport import OneBotTransport


@dataclass(frozen=True, slots=True)
class _AsgiSocket:
    websocket: WebSocket

    @property
    def headers(self) -> Mapping[str, str]:
        return self.websocket.headers

    async def accept(self) -> None:
        await self.websocket.accept()

    async def receive(self) -> str | bytes:
        try:
            frame = await self.websocket.receive()
        except WebSocketDisconnect:
            raise ConnectionError from None
        if frame["type"] == "websocket.disconnect":
            raise ConnectionError
        if (text := frame.get("text")) is not None:
            return text
        if (data := frame.get("bytes")) is not None:
            return data
        raise ConnectionError

    async def send(self, text: str) -> None:
        try:
            await self.websocket.send_text(text)
        except WebSocketDisconnect:
            raise ConnectionError from None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self.websocket.application_state is not WebSocketState.DISCONNECTED:
            await self.websocket.close(code, reason)


@dataclass(frozen=True, slots=True)
class OneBotASGI:
    transport: OneBotTransport

    def install(self, app: FastAPI) -> None:
        for path in ("/onebot/v11/", "/onebot/v11/http", "/onebot/v11/http/"):
            app.add_api_route(
                path,
                self.http,
                methods=["POST"],
                name="OneBot HTTP",
                include_in_schema=False,
            )
        for path in ("/onebot/v11/", "/onebot/v11/ws", "/onebot/v11/ws/"):
            app.add_api_websocket_route(path, self.websocket, name="OneBot WS")

    async def http(self, request: Request) -> Response:
        result = self.transport.http_receiver.receive(
            request.headers, await request.body()
        )
        return Response(result.content, status_code=result.status)

    async def websocket(self, websocket: WebSocket) -> None:
        await self.transport.reverse_server.handle(_AsgiSocket(websocket))
