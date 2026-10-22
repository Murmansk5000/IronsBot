# SPDX-License-Identifier: MIT
"""OneBot HTTP transport using the application's existing HTTP client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from ironsbot.integrations.onebot.errors import OneBotTransportError
from ironsbot.integrations.onebot.http_api import OneBotHttpRequest, OneBotHttpResponse


@dataclass(frozen=True, slots=True)
class HttpxOneBotExchange:
    client: httpx.AsyncClient

    async def __call__(self, request: OneBotHttpRequest) -> OneBotHttpResponse:
        try:
            response = await self.client.request(
                "POST",
                request.url,
                headers=dict(request.headers),
                content=request.body,
                timeout=request.timeout,
                follow_redirects=True,
            )
        except (httpx.RequestError, OSError, asyncio.TimeoutError):
            raise OneBotTransportError from None
        return OneBotHttpResponse(response.status_code, response.content)
