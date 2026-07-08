# SPDX-License-Identifier: MIT
from nonebot.plugin import PluginMetadata

from ironsbot.integrations.http_client import (
    GetHttpCacheClient,
    GetHttpOriginClient,
    HttpCacheClientNotInitializedError,
    HttpOriginClientNotInitializedError,
    _close_http_client,
    _http_client_instances,
    get_http_cache_client,
    get_http_origin_client,
)

__plugin_meta__ = PluginMetadata(
    name="HTTP 缓存客户端",
    description="管理全局共享的 hishel HTTP 缓存客户端生命周期",
    usage="其他插件通过 require 后使用 HttpCacheClient 依赖注入获取客户端实例",
)

__all__ = [
    "GetHttpCacheClient",
    "GetHttpOriginClient",
    "HttpCacheClientNotInitializedError",
    "HttpOriginClientNotInitializedError",
    "_close_http_client",
    "_http_client_instances",
    "get_http_cache_client",
    "get_http_origin_client",
]
