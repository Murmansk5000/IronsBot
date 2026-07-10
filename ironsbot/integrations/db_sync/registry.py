# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.log import logger

from ironsbot.integrations.db_sync import state
from ironsbot.integrations.db_sync.models import GetFingerprintFn, SyncEntry

if TYPE_CHECKING:
    from ironsbot.config.models.runtime import RemoteBuildConfig


def is_sync_running() -> bool:
    return state.sync_all_lock.locked() or any(
        state.get_lock(name).locked()
        for name in state.registered_syncs
    )


def register_database(  # noqa: PLR0913
    name: str,
    *,
    sync_url: str,
    sync_interval_minutes: int = 60,
    get_fingerprint: GetFingerprintFn | None = None,
    local_path: str | None = None,
    remote_build: RemoteBuildConfig | None = None,
) -> None:
    """登记一个远程同步数据库，运行时再准备内存引擎和同步任务。"""
    if name in state.registered_syncs or name in state.registered_local_databases:
        logger.warning(f"数据库 '{name}' 已注册，跳过重复注册")
        return

    state.registered_syncs[name] = SyncEntry(
        sync_url,
        sync_interval_minutes,
        get_fingerprint,
        local_path,
        remote_build,
    )
    logger.debug(f"已登记远程同步数据库 '{name}'")


def register_local_database(name: str, *, file_path: str) -> None:
    """注册一个从本地文件加载的只读内存数据库，不设置自动同步。"""
    if name in state.registered_syncs or name in state.registered_local_databases:
        logger.warning(f"数据库 '{name}' 已注册，跳过重复注册")
        return

    state.registered_local_databases[name] = file_path
    logger.debug(f"已登记本地数据库 '{name}': {file_path}")
