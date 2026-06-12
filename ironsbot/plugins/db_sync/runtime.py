# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from nonebot import get_driver, require
from nonebot.log import logger

from ironsbot.plugins import db_sync

from .config import get_data_sync_config

_db_sync_runtime_state = {"registered": False}


def _register_interval_jobs(scheduler: Any) -> None:
    if not get_data_sync_config().interval_enabled:
        for name in db_sync._registered_syncs:
            logger.debug(f"已注册数据库 '{name}'，自动定时同步已关闭")
        return

    for name, entry in db_sync._registered_syncs.items():
        scheduler.add_job(
            db_sync.run_sync_database,
            "interval",
            args=[name],
            minutes=entry.sync_interval_minutes,
            id=f"db_sync_{name}",
            replace_existing=True,
        )
        logger.debug(
            f"已注册数据库 '{name}'，同步间隔: {entry.sync_interval_minutes} 分钟"
        )


async def _start_db_sync_runtime(scheduler: Any) -> None:
    if not db_sync._registered_syncs and not db_sync._registered_local_databases:
        logger.debug("无已注册的同步数据库，db_sync 插件未激活")
        return

    for name, entry in db_sync._registered_syncs.items():
        db_sync._prepare_remote_database(name)
        logger.info(
            f"数据库 '{name}' 同步已启动，同步间隔: {entry.sync_interval_minutes} 分钟"
        )

    for name, file_path in db_sync._registered_local_databases.items():
        db_sync._prepare_local_database(name, file_path)

    _register_interval_jobs(scheduler)

    for name in db_sync._registered_syncs:
        db_sync.load_cached_database(name)

    # Keep startup sync behind a switch to avoid slow container startup.
    if not get_data_sync_config().on_startup:
        logger.info("启动时数据库同步已关闭，可由超级管理员发送“/更新数据”手动同步")
        return

    async with db_sync._sync_all_lock:
        for name in db_sync._registered_syncs:
            await db_sync.sync_database(name)


def _setup_db_sync_runtime(driver: Any, scheduler: Any) -> None:
    if _db_sync_runtime_state["registered"]:
        return

    @driver.on_startup
    async def _start_db_sync_on_startup() -> None:
        await _start_db_sync_runtime(scheduler)

    _db_sync_runtime_state["registered"] = True


def setup_db_sync_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_db_sync_runtime(get_driver(), scheduler)


__all__ = ["setup_db_sync_runtime"]
