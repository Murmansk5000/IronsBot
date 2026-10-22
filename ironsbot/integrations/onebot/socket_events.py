# SPDX-License-Identifier: MIT
"""One framing, RPC-receipt and event handoff contract for both WS directions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.integrations.onebot.websocket_session import OneBotWebSocketSession


class OneBotSocket(Protocol):
    async def receive(self) -> str | bytes: ...

    async def send(self, text: str) -> None: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...


def decode_socket_frame(raw: str | bytes) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        message = "OneBot frame must be an object"
        raise TypeError(message)
    return payload


@dataclass(frozen=True, slots=True)
class OneBotSocketEvents:
    spawn: TaskSpawner
    on_event: Callable[
        [OneBotWebSocketSession, dict[str, Any]], Coroutine[Any, Any, None]
    ]

    async def receive(
        self,
        socket: OneBotSocket,
        session: OneBotWebSocketSession,
        *,
        stopping: Callable[[], bool],
    ) -> None:
        while not stopping():
            raw = await socket.receive()
            if stopping():
                return
            payload = decode_socket_frame(raw)
            if session.receive(payload):
                continue
            if str(payload.get("self_id", "")) != session.self_id:
                message = "OneBot frame does not match connection"
                raise ValueError(message)
            coroutine = self.on_event(session, payload)
            try:
                self.spawn(coroutine, name="onebot.event")
            except BaseException:
                coroutine.close()
                raise
