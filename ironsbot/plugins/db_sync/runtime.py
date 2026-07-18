# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.log import logger

from ironsbot.integrations.db_sync import runner as db_sync_runner
from ironsbot.integrations.db_sync import state as db_sync_state
from ironsbot.integrations.scheduler.jobs import JobRegistry

if TYPE_CHECKING:
    from ironsbot.config.models.runtime import DataSyncConfig

DB_SYNC_JOB_PREFIX = "db_sync_"


def _register_interval_jobs(
    scheduler: Any,
    config: DataSyncConfig,
) -> None:
    if not config.interval_enabled:
        for name in db_sync_state.registered_syncs:
            logger.debug(f"已注册数据库 '{name}'，自动定时同步已关闭")
        return

    registry = JobRegistry(scheduler, prefix=DB_SYNC_JOB_PREFIX)
    for name, entry in db_sync_state.registered_syncs.items():
        registry.add(
            db_sync_runner.run_sync_database,
            "interval",
            args=[name],
            minutes=entry.sync_interval_minutes,
            job_id=name,
        )
        logger.debug(
            f"已注册数据库 '{name}'，同步间隔: {entry.sync_interval_minutes} 分钟"
        )


async def start_db_sync(
    scheduler: Any,
    config: DataSyncConfig,
    github_token: str,
) -> str | None:
    if (
        not db_sync_state.registered_syncs
        and not db_sync_state.registered_local_databases
    ):
        logger.debug("无已注册的同步数据库，db_sync 插件未激活")
        return None

    for name, entry in db_sync_state.registered_syncs.items():
        db_sync_runner.prepare_remote_database(name)
        logger.info(
            f"数据库 '{name}' 同步已启动，同步间隔: {entry.sync_interval_minutes} 分钟"
        )

    for name, file_path in db_sync_state.registered_local_databases.items():
        db_sync_runner.prepare_local_database(name, file_path)

    _register_interval_jobs(scheduler, config)

    # Keep startup sync behind a switch to avoid slow container startup.
    if not config.on_startup:
        for name in db_sync_state.registered_syncs:
            db_sync_runner.load_cached_database(name)
        logger.info("启动时数据库同步已关闭，可由超级管理员发送“/更新数据”手动同步")
        return None

    trigger_remote_build = getattr(config, "startup_trigger_remote_build", False)
    logger.info(
        "启动时数据库同步已开启"
        + ("，将触发远程构建流水线" if trigger_remote_build else "")
    )
    did_run, results = await db_sync_runner.run_sync_all_databases(
        github_token=github_token,
        trigger_remote_build=trigger_remote_build,
    )
    if not did_run:
        for name in db_sync_state.registered_syncs:
            db_sync_runner.load_cached_database(name)
    else:
        for name, ok in results.items():
            if not ok:
                db_sync_runner.load_cached_database(name)

    return db_sync_runner.format_sync_result_notice(
        results if did_run else {},
        title_prefix="启动数据同步",
    )


__all__ = ["start_db_sync"]
