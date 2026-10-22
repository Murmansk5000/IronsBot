# SPDX-License-Identifier: MIT
"""Use application-owned HTTP resources for the native renderer's callbacks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from ironsbot.integrations.http.clients import HttpClients

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HtmlkitResources:
    clients: HttpClients

    async def image(self, url: str) -> bytes | None:
        if url.startswith("data:"):
            from nonebot_plugin_htmlkit import data_scheme_img_fetcher

            return await data_scheme_img_fetcher(url)
        if url.startswith("file://"):
            from nonebot_plugin_htmlkit import filesystem_img_fetcher

            return await filesystem_img_fetcher(url)
        return await self._network(url)

    async def css(self, url: str) -> str | None:
        if url.startswith("data:"):
            from nonebot_plugin_htmlkit import data_scheme_css_fetcher

            return await data_scheme_css_fetcher(url)
        if url.startswith("file://"):
            from nonebot_plugin_htmlkit import filesystem_css_fetcher

            return await filesystem_css_fetcher(url)
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
