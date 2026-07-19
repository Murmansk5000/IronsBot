# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ironsbot.config.models.operations import DataSyncConfig
    from ironsbot.services.operations.scheduler import Scheduler

logger = logging.getLogger(__name__)
BUSY_MESSAGE = "⏳ 数据更新正在进行中，请稍后再试。"


class DataSyncBackend(Protocol):
    def has_databases(self) -> bool: ...
    def remote_names(self) -> tuple[str, ...]: ...
    def remote_build_names(self) -> tuple[str, ...]: ...
    def schedules(self) -> tuple[tuple[str, int], ...]: ...
    def is_running(self) -> bool: ...
    def prepare_all(self) -> None: ...
    def load_all_cached(self) -> None: ...
    def load_failed_cached(self, results: dict[str, bool]) -> None: ...
    async def run_sync_database(self, name: str) -> bool: ...
    async def run_sync_all_databases(
        self,
        *,
        github_token: str,
        trigger_remote_build: bool = False,
        force_remote_build: bool = False,
    ) -> tuple[bool, dict[str, bool]]: ...
    def format_remote_build_failures(self, failed_names: list[str]) -> str: ...
    def format_sync_statuses(self, results: dict[str, bool]) -> str: ...
    def format_sync_result_notice(
        self,
        results: dict[str, bool],
        *,
        title_prefix: str = "数据更新",
    ) -> str: ...
    def skipped_names(self, results: dict[str, bool]) -> list[str]: ...


class DataSyncService:
    def __init__(self, config: DataSyncConfig, backend: DataSyncBackend) -> None:
        self._config = config
        self._backend = backend

    def prepare_manual(self, *, force: bool) -> tuple[str, bool]:
        names = self._backend.remote_names()
        if not names:
            return "当前没有已注册的远程同步数据库。", False
        if self._backend.is_running():
            return BUSY_MESSAGE, False

        builds = self._backend.remote_build_names()
        if not builds:
            return f"开始更新数据：{', '.join(names)}，请稍等。", True
        action = "强制远程重建数据" if force else "检查远程数据更新"
        return (
            f"开始{action}：{', '.join(builds)}；"
            f"随后更新数据：{', '.join(names)}，请稍等。",
            True,
        )

    async def run_manual(self, *, force: bool) -> str:
        did_run, results = await self._backend.run_sync_all_databases(
            github_token=self._config.github_token,
            trigger_remote_build=True,
            force_remote_build=force,
        )
        if not did_run:
            return BUSY_MESSAGE
        return self._format_manual_result(results)

    async def startup(self, scheduler: Scheduler) -> str | None:
        if not self._backend.has_databases():
            logger.debug("无已注册的数据源，数据同步未激活")
            return None

        self._backend.prepare_all()
        self._register_jobs(scheduler)
        if not self._config.on_startup:
            self._backend.load_all_cached()
            logger.info("启动同步已关闭，可由超级管理员发送“/更新数据”手动同步")
            return None

        trigger_build = self._config.startup_trigger_remote_build
        did_run, results = await self._backend.run_sync_all_databases(
            github_token=self._config.github_token,
            trigger_remote_build=trigger_build,
        )
        if did_run:
            self._backend.load_failed_cached(results)
        else:
            self._backend.load_all_cached()
        return self._backend.format_sync_result_notice(
            results if did_run else {},
            title_prefix="启动数据同步",
        )

    def _register_jobs(self, scheduler: Scheduler) -> None:
        for name, minutes in self._backend.schedules():
            if not self._config.interval_enabled:
                logger.debug("已注册数据库 %r，自动定时同步已关闭", name)
                continue
            scheduler.add_job(
                self._backend.run_sync_database,
                "interval",
                args=[name],
                minutes=minutes,
                id=f"db_sync_{name}",
                replace_existing=True,
            )

    def _format_manual_result(self, results: dict[str, bool]) -> str:
        failed = [name for name, ok in results.items() if not ok]
        succeeded = [name for name, ok in results.items() if ok]
        status = self._backend.format_sync_statuses(results)
        status_extra = f"\n{status}" if status else ""
        if failed:
            remote = self._backend.format_remote_build_failures(failed)
            remote_extra = f"\n{remote}" if remote else ""
            return (
                "数据更新完成，但有失败项。\n"
                f"成功：{', '.join(succeeded) if succeeded else '无'}\n"
                f"失败：{', '.join(failed)}{status_extra}{remote_extra}\n"
                "请查看容器日志确认网络或下载错误。"
            )

        skipped = self._backend.skipped_names(results)
        title = (
            f"数据已是最新，无需更新：{', '.join(skipped)}"
            if skipped and len(skipped) == len(results)
            else f"数据更新完成：{', '.join(succeeded)}"
        )
        return f"{title}{status_extra}"
