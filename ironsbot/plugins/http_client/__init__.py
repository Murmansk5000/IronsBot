# SPDX-License-Identifier: MIT
from typing import TypedDict

from hishel.httpx import AsyncCacheClient
from httpx import AsyncClient
from nonebot import logger
from nonebot.params import Depends
from nonebot.plugin import PluginMetadata


class HttpCacheClientNotInitializedError(RuntimeError):
    """Raised when the cached HTTP client is requested before startup."""


class HttpOriginClientNotInitializedError(RuntimeError):
    """Raised when the plain HTTP client is requested before startup."""


class _HttpClientInstances(TypedDict):
    cache_client: AsyncCacheClient | None
    origin_client: AsyncClient | None

__plugin_meta__ = PluginMetadata(
    name="HTTP 缓存客户端",
    description="管理全局共享的 hishel HTTP 缓存客户端生命周期",
    usage="其他插件通过 require 后使用 HttpCacheClient 依赖注入获取客户端实例",
)
_http_client_instances: _HttpClientInstances = {
    "cache_client": None,
    "origin_client": None,
}


def get_http_cache_client() -> AsyncCacheClient:
    """获取全局 HTTP 缓存客户端实例。"""
    client = _http_client_instances["cache_client"]
    if client is None:
        raise HttpCacheClientNotInitializedError
    return client


def get_http_origin_client() -> AsyncClient:
    """获取全局 HTTP 客户端实例。"""
    client = _http_client_instances["origin_client"]
    if client is None:
        raise HttpOriginClientNotInitializedError
    return client


async def _close_http_client(client: AsyncClient | None) -> None:
    if client is None:
        return

    try:
        await client.aclose()
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).error("关闭 HTTP 客户端失败")


GetHttpCacheClient = Depends(get_http_cache_client)
GetHttpOriginClient = Depends(get_http_origin_client)
