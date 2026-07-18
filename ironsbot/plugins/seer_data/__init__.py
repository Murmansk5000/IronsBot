# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import logger

from ironsbot.integrations.db_sync.registry import (
    register_database,
    register_local_database,
)

_SEERAPI_DB = "seerapi"
_ALIAS_DB = "aliases"

if TYPE_CHECKING:
    import httpx

    from ironsbot.config.models.runtime import DataSourceConfig, DataSyncConfig
    from ironsbot.integrations.db_sync.models import GetFingerprintFn
    from ironsbot.runtime.matchers import MatcherRegistry



def _register_source(name: str, source: DataSourceConfig) -> None:
    if source.url:
        register_database(
            name,
            sync_url=source.url,
            sync_interval_minutes=source.interval_minutes,
            get_fingerprint=_fingerprint_getter(source.fingerprint_url),
            local_path=source.local_path,
            remote_build=source.remote_build,
        )
    else:
        register_local_database(name, file_path=source.local_path)


def _fingerprint_getter(url: str) -> GetFingerprintFn | None:
    if not url:
        return None

    async def _get_fingerprint(client: httpx.AsyncClient) -> str:
        response = await client.get(url)
        return response.text

    return _get_fingerprint


def install(_registry: MatcherRegistry, config: DataSyncConfig) -> None:
    for name in (_SEERAPI_DB, _ALIAS_DB):
        if source := config.sources.get(name):
            _register_source(name, source)
        else:
            logger.warning(f"数据源 '{name}' 未在 runtime.data_sync.sources 中配置")
