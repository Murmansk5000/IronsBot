# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from ironsbot.services.operations.scheduler import JobRegistry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.config.models.operations import DataSyncConfig
    from ironsbot.services.operations.scheduler import Scheduler

logger = logging.getLogger(__name__)
BUSY_MESSAGE = "⏳ 数据更新正在进行中，请稍后再试。"


class ManualDataSyncAction(str, Enum):
    SYNC_PUBLISHED = "sync_published"
    UPDATE_UPSTREAM = "update_upstream"


@dataclass(frozen=True, slots=True)
class ManualDataSyncOption:
    key: str
    action: ManualDataSyncAction
    label: str


class DataSyncBackend(Protocol):
    def has_databases(self) -> bool: ...
    def remote_names(self) -> tuple[str, ...]: ...
    def remote_build_names(self) -> tuple[str, ...]: ...
    def schedules(self) -> tuple[tuple[str, int, int], ...]: ...
    def is_running(self) -> bool: ...
    async def check_all_databases(
        self,
    ) -> tuple[bool, Mapping[str, object]]: ...
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
    def format_local_versions(self, names: tuple[str, ...]) -> str: ...
    def format_sync_statuses(self, results: dict[str, bool]) -> str: ...
    def format_sync_check_statuses(
        self,
        statuses: Mapping[str, object],
    ) -> str: ...
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

    async def prepare_manual(self, *, force: bool) -> tuple[str, bool]:
        names = self._backend.remote_names()
        if not names:
            return "当前没有已注册的远程同步数据库。", False
        if self._backend.is_running():
            return BUSY_MESSAGE, False

        checked, statuses = await self._backend.check_all_databases()
        if not checked:
            return BUSY_MESSAGE, False

        failed = [
            name
            for name, status in statuses.items()
            if not bool(getattr(status, "ok", False))
        ]
        check_status = self._backend.format_sync_check_statuses(statuses)
        if failed:
            return (
                "数据更新检查失败，未执行更新："
                f"{', '.join(failed)}\n{check_status}",
                False,
            )

        changed = [
            name
            for name, status in statuses.items()
            if not bool(getattr(status, "skipped", False))
        ]
        summary = (
            f"检测到已发布的新数据：{', '.join(changed)}"
            if changed
            else "当前已发布的数据已是最新"
        )
        options = self.manual_options(force=force)
        option_lines = ["请选择后续操作："]
        option_lines.extend(f"{option.key}. {option.label}" for option in options)
        option_lines.append("0. 退出")
        return (
            f"数据更新检查完成。{summary}\n{check_status}\n\n"
            + "\n".join(option_lines),
            True,
        )

    def manual_options(self, *, force: bool) -> tuple[ManualDataSyncOption, ...]:
        options = [
            ManualDataSyncOption(
                key="1",
                action=ManualDataSyncAction.SYNC_PUBLISHED,
                label="同步已发布数据",
            )
        ]
        if self._backend.remote_build_names():
            options.append(
                ManualDataSyncOption(
                    key="2",
                    action=ManualDataSyncAction.UPDATE_UPSTREAM,
                    label=(
                        "强制检查上游并重建后同步数据"
                        if force
                        else "检查上游并构建后同步数据"
                    ),
                )
            )
        return tuple(options)

    def manual_action_for_choice(
        self,
        text: str,
        *,
        force: bool,
    ) -> ManualDataSyncAction | None:
        choice = text.strip()
        for option in self.manual_options(force=force):
            if choice == option.key:
                return option.action
        return None

    async def run_manual(
        self,
        *,
        action: ManualDataSyncAction,
        force: bool,
    ) -> str:
        trigger_remote_build = action is ManualDataSyncAction.UPDATE_UPSTREAM
        did_run, results = await self._backend.run_sync_all_databases(
            github_token=self._config.github_token,
            trigger_remote_build=trigger_remote_build,
            force_remote_build=force and trigger_remote_build,
        )
        if not did_run:
            return BUSY_MESSAGE
        return self._format_manual_result(
            results,
            downstream_publication_pending=trigger_remote_build and any(
                source.remote_build.enabled
                and source.remote_build.downstream_publication_pending
                for source in self._config.sources.values()
            ),
        )

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
        for name, minutes, second in self._backend.schedules():
            if not self._config.interval_enabled:
                logger.debug("已注册数据库 %r，自动定时同步已关闭", name)
                continue
            JobRegistry(scheduler).add_wall_clock_interval(
                self._backend.run_sync_database,
                args=[name],
                minutes=minutes,
                offset_seconds=second,
                job_id=f"db_sync_{name}",
            )

    def _format_manual_result(
        self,
        results: dict[str, bool],
        *,
        downstream_publication_pending: bool = False,
    ) -> str:
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
        downstream_notice = (
            "\napi-data 发布后会自动派发下游 SeerAPI 构建；"
            "新数据库发布后，机器人会在最多 5 分钟内热同步。"
            if downstream_publication_pending
            else ""
        )
        return f"{title}{status_extra}{downstream_notice}"
