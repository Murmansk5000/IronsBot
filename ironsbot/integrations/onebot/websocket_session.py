# SPDX-License-Identifier: MIT
"""Connection-scoped OneBot RPC, independent of event and hosting frameworks."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from itertools import count
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ironsbot.integrations.onebot.api_results import onebot_api_result
from ironsbot.integrations.onebot.errors import (
    OneBotActionError,
    OneBotTransportError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping


@dataclass(slots=True)
class _Request:
    result: asyncio.Future[object]
    submitted: bool = False


class OneBotWebSocketSession:
    def __init__(
        self,
        account_id: str,
        send: Callable[[str], Awaitable[None]],
        *,
        timeout: float | None,
    ) -> None:
        if timeout is not None and timeout <= 0:
            message = "OneBot API timeout must be positive"
            raise ValueError(message)
        self.self_id = account_id
        self._send = send
        self._timeout = timeout
        self._prefix = uuid4().hex
        self._sequence = count()
        self._pending: dict[str, _Request] = {}
        self._send_lock = asyncio.Lock()
        self._closed = False

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def call_api(self, api: str, **data: Any) -> object:
        timeout = data.pop("_timeout", self._timeout)
        if self._closed:
            raise OneBotTransportError(definitely_not_sent=True)
        echo = f"{self._prefix}:{next(self._sequence)}"
        # Encode before registration: invalid caller data cannot leave a waiter.
        payload = json.dumps({"action": api, "params": data, "echo": echo})
        request = _Request(asyncio.get_running_loop().create_future())
        self._pending[echo] = request
        try:
            async with asyncio.timeout(timeout):
                async with self._send_lock:
                    if self._closed:
                        raise OneBotTransportError(definitely_not_sent=True)
                    request.submitted = True
                    try:
                        await self._send(payload)
                    except ConnectionError:
                        self.close()
                        raise
                return await request.result
        finally:
            self._pending.pop(echo, None)
            if request.result.done() and not request.result.cancelled():
                request.result.exception()
            else:
                request.result.cancel()

    def receive(self, payload: Mapping[str, object]) -> bool:
        """Consume all response frames, including late or unknown echoes."""
        if "echo" not in payload or "post_type" in payload:
            return False
        echo = payload["echo"]
        request = self._pending.get(echo) if isinstance(echo, str) else None
        if request is None or request.result.done():
            return True
        try:
            result = onebot_api_result(payload)
        except OneBotActionError as error:
            request.result.set_exception(error)
        else:
            request.result.set_result(result)
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for request in self._pending.values():
            if not request.result.done():
                request.result.set_exception(
                    OneBotTransportError(definitely_not_sent=not request.submitted)
                )
