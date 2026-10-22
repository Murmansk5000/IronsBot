# SPDX-License-Identifier: MIT
"""Authenticated OneBot HTTP event reception independent of its ASGI host."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping
    from typing import Any

    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.integrations.onebot.connections import OneBotConnection


@dataclass(frozen=True, slots=True)
class OneBotHttpResult:
    status: int
    content: str = ""


class OneBotHttpReceiver:
    def __init__(
        self,
        *,
        secret: str | None,
        spawn: TaskSpawner,
        connection: Callable[[str], OneBotConnection],
        on_event: Callable[
            [OneBotConnection, dict[str, Any]], Coroutine[Any, Any, None]
        ],
    ) -> None:
        self.secret = secret
        self.spawn = spawn
        self.connection = connection
        self.on_event = on_event
        self._closing = False

    def receive(  # noqa: PLR0911 - explicit HTTP authentication and source rejections
        self, headers: Mapping[str, str], body: str | bytes | None
    ) -> OneBotHttpResult:
        if self._closing:
            return OneBotHttpResult(503, "OneBot receiver stopping")
        account_id = headers.get("x-self-id", "")
        if not account_id.isascii() or not account_id.isdecimal():
            return OneBotHttpResult(400, "Invalid X-Self-ID Header")
        rejection = self._check_signature(headers, body)
        if rejection is not None:
            return rejection
        if not body:
            return OneBotHttpResult(400, "Invalid request body")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            return OneBotHttpResult(400, "Invalid request body")
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("post_type"), str)
            or str(payload.get("self_id", "")) != account_id
        ):
            return OneBotHttpResult(400, "Invalid OneBot event source")
        connection = self.connection(account_id)
        coroutine = self.on_event(connection, payload)
        try:
            self.spawn(coroutine, name="onebot.event")
        except BaseException:
            coroutine.close()
            raise
        return OneBotHttpResult(204)

    def _check_signature(
        self, headers: Mapping[str, str], body: str | bytes | None
    ) -> OneBotHttpResult | None:
        if not self.secret:
            return None
        supplied = headers.get("x-signature", "")
        if not supplied:
            return OneBotHttpResult(401, "Missing Signature")
        if body is None:
            return OneBotHttpResult(400, "Missing Content")
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        expected = "sha1=" + hmac.new(self.secret.encode(), raw, "sha1").hexdigest()
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            return OneBotHttpResult(403, "Signature is invalid")
        return None

    def close(self) -> None:
        self._closing = True
