# SPDX-License-Identifier: MIT
from __future__ import annotations

from hishel.httpx import AsyncCacheClient
from httpx import AsyncClient
from nonebot import logger

from ironsbot.integrations.http_client import _close_http_client, _http_client_instances


async def initialize_http_clients() -> None:
    _http_client_instances["cache_client"] = AsyncCacheClient()
    _http_client_instances["origin_client"] = AsyncClient()
    logger.info("HTTP 客户端已初始化")


async def shutdown_http_clients() -> None:
    await _close_http_client(_http_client_instances["cache_client"])
    await _close_http_client(_http_client_instances["origin_client"])


__all__ = ["initialize_http_clients", "shutdown_http_clients"]
