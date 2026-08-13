# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass, field

from hishel.httpx import AsyncCacheClient
from httpx import AsyncClient

logger = logging.getLogger(__name__)

# HTTPX otherwise builds a fresh SSL context for every long-lived client.  The
# cache and origin clients use the same system trust store, so one immutable
# process-wide context avoids repeated CA bundle loading during startup.
_DEFAULT_TLS_CONTEXT = ssl.create_default_context()


def _cache_client() -> AsyncClient:
    return AsyncCacheClient(verify=_DEFAULT_TLS_CONTEXT)


def _origin_client() -> AsyncClient:
    return AsyncClient(verify=_DEFAULT_TLS_CONTEXT)


@dataclass(slots=True)
class HttpClients:
    cache: AsyncClient = field(default_factory=_cache_client)
    origin: AsyncClient = field(default_factory=_origin_client)

    async def close(self) -> None:
        for client in (self.cache, self.origin):
            try:
                await client.aclose()
            except Exception:  # noqa: PERF203
                logger.exception("关闭 HTTP 客户端失败")
