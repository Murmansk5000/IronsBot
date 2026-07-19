# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from hishel.httpx import AsyncCacheClient
from httpx import AsyncClient

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class HttpClients:
    cache: AsyncClient = field(default_factory=AsyncCacheClient)
    origin: AsyncClient = field(default_factory=AsyncClient)
    cache_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def close(self) -> None:
        for client in (self.cache, self.origin):
            try:
                await client.aclose()
            except Exception:  # noqa: PERF203
                logger.exception("关闭 HTTP 客户端失败")
