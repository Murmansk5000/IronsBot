# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from hishel.httpx import AsyncCacheClient
from httpx import AsyncClient
from nonebot import get_driver, logger

from . import _close_http_client, _http_client_instances

_http_client_runtime_state = {"registered": False}


async def _initialize_http_clients() -> None:
    _http_client_instances["cache_client"] = AsyncCacheClient()
    _http_client_instances["origin_client"] = AsyncClient()
    logger.info("HTTP 客户端已初始化")


async def _shutdown_http_clients() -> None:
    await _close_http_client(_http_client_instances["cache_client"])
    await _close_http_client(_http_client_instances["origin_client"])


def _setup_http_client_runtime(driver: Any) -> None:
    if _http_client_runtime_state["registered"]:
        return

    driver.on_startup(_initialize_http_clients)
    driver.on_shutdown(_shutdown_http_clients)
    _http_client_runtime_state["registered"] = True


def setup_http_client_runtime() -> None:
    _setup_http_client_runtime(get_driver())


__all__ = ["setup_http_client_runtime"]
