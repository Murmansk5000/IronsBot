# SPDX-License-Identifier: MIT
"""OneBot HTTP action calls without framework HTTP models or retry policy."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Protocol

from ironsbot.integrations.onebot.api_results import onebot_api_result
from ironsbot.integrations.onebot.errors import OneBotTransportError

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class OneBotHttpRequest:
    url: str
    body: str
    headers: Mapping[str, str]
    timeout: float | None


@dataclass(frozen=True, slots=True)
class OneBotHttpResponse:
    status: int
    content: str | bytes | None


class OneBotHttpExchange(Protocol):
    async def __call__(self, request: OneBotHttpRequest) -> OneBotHttpResponse: ...


class OneBotHttpApi:
    def __init__(
        self,
        *,
        api_roots: Mapping[str, str],
        access_token: str | None,
        timeout: float | None,
        request: OneBotHttpExchange,
    ) -> None:
        self.api_roots = dict(api_roots)
        self.access_token = access_token
        self.timeout = timeout
        self.request = request
        self._closed = False

    async def call(self, account: str, api: str, **data: Any) -> object:
        root = self.api_roots.get(account)
        if self._closed or not root:
            raise OneBotTransportError(definitely_not_sent=True)
        timeout = data.pop("_timeout", self.timeout)
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        request = OneBotHttpRequest(
            root.rstrip("/") + "/" + api, json.dumps(data), headers, timeout
        )
        try:
            async with asyncio.timeout(timeout):
                response = await self.request(request)
        except (OSError, asyncio.TimeoutError):
            raise OneBotTransportError from None
        if (
            not HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES
            or not response.content
        ):
            raise OneBotTransportError
        try:
            payload = json.loads(response.content)
        except (ValueError, UnicodeError):
            raise OneBotTransportError from None
        return onebot_api_result(payload)

    def close(self) -> None:
        self._closed = True
