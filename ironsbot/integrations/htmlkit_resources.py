# SPDX-License-Identifier: MIT
"""Use application-owned HTTP resources for the native renderer's callbacks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from ironsbot.integrations.litehtml.local_resources import local_css, local_image

if TYPE_CHECKING:
    from ironsbot.integrations.http.clients import HttpClients

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HtmlkitResources:
    clients: HttpClients

    async def image(self, url: str) -> bytes | None:
        if url.startswith(("data:", "file://")):
            return await local_image(url)
        return await self._network(url)

    async def css(self, url: str) -> str | None:
        if url.startswith(("data:", "file://")):
            return await local_css(url)
        content = await self._network(url)
        if content is None:
            return None
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("renderer CSS decoding failed")
            return None

    async def _network(self, url: str) -> bytes | None:
        if not url.startswith(("https://", "http://")):
            return None
        try:
            response = await self.clients.origin.get(url, follow_redirects=True)
        except (httpx.RequestError, OSError) as error:
            logger.warning("renderer resource request failed: %s", type(error).__name__)
            return None
        return response.content
