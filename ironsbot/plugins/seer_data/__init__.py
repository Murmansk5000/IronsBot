# SPDX-License-Identifier: MIT
import httpx
from nonebot import logger, require
from nonebot.plugin import PluginMetadata

from ironsbot.config.loader import get_app_config
from ironsbot.config.models.app import AppConfig

require("ironsbot.plugins.db_sync")
require("ironsbot.plugins.http_client")

from ironsbot.config.models.runtime import RemoteBuildConfig
from ironsbot.integrations.db_sync.models import GetFingerprintFn
from ironsbot.integrations.db_sync.registry import (
    register_database,
    register_local_database,
)

_SEERAPI_DB = "seerapi"
_ALIAS_DB = "aliases"


def _register(  # noqa: PLR0913
    name: str,
    sync_url: str,
    interval: int,
    local_path: str,
    get_fingerprint: GetFingerprintFn | None = None,
    remote_build: RemoteBuildConfig | None = None,
) -> None:
    if sync_url:
        register_database(
            name,
            sync_url=sync_url,
            sync_interval_minutes=interval,
            get_fingerprint=get_fingerprint,
            local_path=local_path,
            remote_build=remote_build,
        )
    else:
        register_local_database(name, file_path=local_path)


def _fingerprint_getter(url: str) -> GetFingerprintFn | None:
    if not url:
        return None

    async def _get_fingerprint(client: httpx.AsyncClient) -> str:
        response = await client.get(url)
        return response.text

    return _get_fingerprint


def _register_source(name: str) -> None:
    source = get_app_config().runtime.data_sync.sources.get(name)
    if source is None:
        logger.warning(f"数据源 '{name}' 未在 runtime.data_sync.sources 中配置")
        return

    _register(
        name,
        source.url,
        source.interval_minutes,
        source.local_path,
        _fingerprint_getter(source.fingerprint_url),
        source.remote_build,
    )


_register_source(_SEERAPI_DB)
_register_source(_ALIAS_DB)

__plugin_meta__ = PluginMetadata(
    name="赛尔号数据",
    description="赛尔号 API 数据库同步、查询依赖与游戏资源图片获取",
    usage=(
        "加载后注册 seerapi 与 aliases 数据源；"
        "查询和图片访问使用 integrations.seer_data。"
    ),
    config=AppConfig,
)
