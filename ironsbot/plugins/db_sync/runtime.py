# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from nonebot import get_driver, require
from nonebot.log import logger

from ironsbot.plugins import db_sync
from ironsbot.shared.scheduler import JobRegistry

from .config import get_data_sync_config

_db_sync_runtime_state = {"registered": False}
_startup_sync_state: dict[str, str | None] = {"notice": None}
DB_SYNC_JOB_PREFIX = "db_sync_"


def get_startup_sync_notice() -> str | None:
    return _startup_sync_state["notice"]


def _register_interval_jobs(scheduler: Any) -> None:
    if not get_data_sync_config().interval_enabled:
        for name in db_sync._registered_syncs:
            logger.debug(f"已注册数据库 '{name}'，自动定时同步已关闭")
        return

    registry = JobRegistry(scheduler, prefix=DB_SYNC_JOB_PREFIX)
    for name, entry in db_sync._registered_syncs.items():
        registry.add(
            db_sync.run_sync_database,
            "interval",
            args=[name],
            minutes=entry.sync_interval_minutes,
            job_id=name,
        )
        logger.debug(
            f"已注册数据库 '{name}'，同步间隔: {entry.sync_interval_minutes} 分钟"
        )


async def _start_db_sync_runtime(scheduler: Any) -> None:
    _startup_sync_state["notice"] = None
    if not db_sync._registered_syncs and not db_sync._registered_local_databases:
        logger.debug("无已注册的同步数据库，db_sync 插件未激活")
        return

    config = get_data_sync_config()
    for name, entry in db_sync._registered_syncs.items():
        db_sync._prepare_remote_database(name)
        logger.info(
            f"数据库 '{name}' 同步已启动，同步间隔: {entry.sync_interval_minutes} 分钟"
        )

    for name, file_path in db_sync._registered_local_databases.items():
        db_sync._prepare_local_database(name, file_path)

    _register_interval_jobs(scheduler)

    # Keep startup sync behind a switch to avoid slow container startup.
    if not config.on_startup:
        for name in db_sync._registered_syncs:
            db_sync.load_cached_database(name)
        logger.info("启动时数据库同步已关闭，可由超级管理员发送“/更新数据”手动同步")
        return

    trigger_remote_build = getattr(config, "startup_trigger_remote_build", False)
    logger.info(
        "启动时数据库同步已开启"
        + ("，将触发远程构建流水线" if trigger_remote_build else "")
    )
    did_run, results = await db_sync.run_sync_all_databases(
        trigger_remote_build=trigger_remote_build
    )
    if not did_run:
        for name in db_sync._registered_syncs:
            db_sync.load_cached_database(name)
    else:
        for name, ok in results.items():
            if not ok:
                db_sync.load_cached_database(name)

    _startup_sync_state["notice"] = db_sync.format_sync_result_notice(
        results if did_run else {},
        title_prefix="启动数据同步",
    )


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


__all__ = ["get_startup_sync_notice", "setup_db_sync_runtime"]
