# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from anyio import Path as AsyncPath
from anyio import to_thread

from ironsbot.integrations.db_sync.github_actions import (
    WorkflowRunResult,
    trigger_and_wait_workflow,
)
from ironsbot.integrations.db_sync.models import SyncEntry, SyncStatus, VersionInfo
from ironsbot.integrations.db_sync.storage import (
    _fetch_remote_timestamp,
    _file_timestamp,
    _fingerprint_content,
    _fingerprint_file,
    _normalize_fingerprint,
    _write_bytes_atomic,
)

from . import formatting as sync_formatting
from . import remote_build as sync_remote_build

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from datetime import datetime

    from ironsbot.config.models.operations import DataSourceConfig
    from ironsbot.integrations.db_registry import DatabaseManager
    from ironsbot.integrations.db_sync.models import GetFingerprintFn
    from ironsbot.runtime.cache_paths import CachePaths


@dataclass(slots=True)
class DatabaseSync:
    databases: DatabaseManager
    cache_paths: CachePaths | None = None
    registered_syncs: dict[str, SyncEntry] = field(default_factory=dict)
    registered_local_databases: dict[str, str] = field(default_factory=dict)
    prepared_databases: set[str] = field(default_factory=set)
    fingerprints: dict[str, str] = field(default_factory=dict)
    last_sync_statuses: dict[str, SyncStatus] = field(default_factory=dict)
    remote_build_results: dict[str, WorkflowRunResult] = field(default_factory=dict)
    _sync_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _sync_all_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def register(self, name: str, source: DataSourceConfig) -> None:
        if source.url:
            self.registered_syncs[name] = SyncEntry(
                sync_url=source.url,
                sync_interval_minutes=source.interval_minutes,
                get_fingerprint=self._fingerprint_getter(source.fingerprint_url),
                local_path=source.local_path,
                remote_build=source.remote_build,
                sync_interval_second=source.interval_second,
            )
            return
        self.registered_local_databases[name] = source.local_path

    def has_databases(self) -> bool:
        return bool(self.registered_syncs or self.registered_local_databases)

    def remote_names(self) -> tuple[str, ...]:
        return tuple(self.registered_syncs)

    def remote_build_names(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, entry in self.registered_syncs.items()
            if entry.remote_build is not None and entry.remote_build.enabled
        )

    def schedules(self) -> tuple[tuple[str, int, int], ...]:
        return tuple(
            (name, entry.sync_interval_minutes, entry.sync_interval_second)
            for name, entry in self.registered_syncs.items()
        )

    def is_running(self) -> bool:
        return self._sync_all_lock.locked() or any(
            self._lock(name).locked() for name in self.registered_syncs
        )

    def prepare_all(self) -> None:
        for name in self.registered_syncs:
            self._prepare_remote_database(name)
        for name, file_path in self.registered_local_databases.items():
            self._prepare_local_database(name, file_path)

    def load_all_cached(self) -> None:
        for name in self.registered_syncs:
            self.load_cached_database(name)

    def load_failed_cached(self, results: dict[str, bool]) -> None:
        for name, ok in results.items():
            if not ok:
                self.load_cached_database(name)

    async def sync_database(  # noqa: C901, PLR0911, PLR0912, PLR0915
        self,
        name: str,
    ) -> bool:
        entry = self.registered_syncs.get(name)
        if entry is None:
            return False

        async with self._lock(name):
            local_before = VersionInfo(
                fingerprint=(
                    _fingerprint_file(entry.local_path)
                    if entry.local_path is not None
                    else None
                ),
                timestamp=(
                    _file_timestamp(entry.local_path)
                    if entry.local_path is not None
                    else None
                ),
            )
            remote = VersionInfo()
            tmp_path: AsyncPath | None = None

            try:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=httpx.Timeout(30.0, read=120.0),
                ) as client:
                    fingerprint: str | None = None
                    if entry.get_fingerprint is not None:
                        try:
                            fingerprint = _normalize_fingerprint(
                                await entry.get_fingerprint(client)
                            )
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                f"获取数据库 '{name}' 指纹失败，将继续执行同步",
                                exc_info=True,
                            )

                    remote = VersionInfo(
                        fingerprint=fingerprint,
                        timestamp=await _fetch_remote_timestamp(client, entry.sync_url),
                    )
                    if self._load_matching_local_cache(
                        name,
                        entry,
                        local_before,
                        remote,
                        fingerprint,
                    ):
                        return True
                    if (
                        fingerprint is not None
                        and fingerprint == self.fingerprints.get(name)
                        and not entry.local_path
                    ):
                        logger.debug(
                            f"数据库 '{name}' 指纹未变化 ({fingerprint})，跳过同步"
                        )
                        self.last_sync_statuses[name] = SyncStatus(
                            ok=True,
                            skipped=True,
                            local_before=local_before,
                            remote=remote,
                            message="内存版本与远端一致，无需更新",
                        )
                        return True

                    logger.info(f"开始从 {entry.sync_url} 同步数据库 '{name}'...")
                    content = bytearray()
                    async with client.stream("GET", entry.sync_url) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            content.extend(chunk)

                content_bytes = bytes(content)
                content_fingerprint = _fingerprint_content(content_bytes)
                download_directory: str | None = None
                if self.cache_paths is not None:
                    downloads_path = self.cache_paths.downloads_dir()
                    downloads_path.mkdir(parents=True, exist_ok=True)
                    download_directory = str(downloads_path)
                fd, tmp_name = tempfile.mkstemp(
                    suffix=".sqlite",
                    dir=download_directory,
                )
                os.close(fd)
                tmp_path = AsyncPath(tmp_name)
                await tmp_path.write_bytes(content_bytes)
                self.databases.load_from_file(name, str(tmp_path))
                cache_saved, local_timestamp_after = await self._save_local_cache(
                    name,
                    entry,
                    content_bytes,
                    local_before,
                )
                self.fingerprints[name] = fingerprint or content_fingerprint
                if remote.fingerprint is None:
                    remote = VersionInfo(
                        fingerprint=content_fingerprint,
                        timestamp=remote.timestamp,
                    )

                size_mb = len(content) / (1024 * 1024)
                logger.info(
                    f"数据库 '{name}' 已同步到内存，源文件大小: {size_mb:.2f} MB"
                )
                self.last_sync_statuses[name] = SyncStatus(
                    ok=cache_saved,
                    skipped=False,
                    local_before=local_before,
                    remote=remote,
                    message=(
                        "已更新"
                        if cache_saved
                        else "已加载到内存，但本地缓存写入失败"
                    ),
                )
                if local_timestamp_after is not None:
                    logger.debug(
                        f"数据库 '{name}' 本地缓存写入时间: "
                        f"{local_timestamp_after.isoformat()}"
                    )
            except httpx.HTTPStatusError as error:
                logger.warning(
                    f"数据库 '{name}' 同步失败（HTTP {error.response.status_code}）："
                    f"{error.request.url}"
                )
                return self._fail(
                    name,
                    local_before,
                    remote,
                    f"HTTP {error.response.status_code}",
                )
            except httpx.TransportError as error:
                message = f"{type(error).__name__}: {error}"
                logger.warning(f"数据库 '{name}' 同步失败（网络连接错误）：{message}")
                return self._fail(name, local_before, remote, message)
            except httpx.HTTPError as error:
                message = f"{type(error).__name__}: {error}"
                logger.warning(
                    f"数据库 '{name}' 同步失败（HTTP 客户端错误）：{message}"
                )
                return self._fail(name, local_before, remote, message)
            except (OSError, ValueError):
                logger.exception(f"数据库 '{name}' 同步失败（文件或导入错误）")
                return self._fail(name, local_before, remote, "文件或导入错误")
            else:
                return cache_saved
            finally:
                if tmp_path is not None:
                    await tmp_path.unlink(missing_ok=True)

    async def run_sync_database(self, name: str) -> bool:
        if self._sync_all_lock.locked():
            logger.info(f"数据库全量同步正在运行，跳过 '{name}' 本次定时同步")
            return False
        if self._lock(name).locked():
            logger.info(f"数据库 '{name}' 正在同步，跳过本次触发")
            return False
        return await self.sync_database(name)

    async def run_sync_all_databases(
        self,
        *,
        github_token: str,
        trigger_remote_build: bool = False,
        force_remote_build: bool = False,
    ) -> tuple[bool, dict[str, bool]]:
        if self._sync_all_lock.locked():
            logger.info("数据库全量同步正在运行，跳过本次手动触发")
            return False, {}

        async with self._sync_all_lock:
            busy_names = [
                name
                for name in self.registered_syncs
                if self._lock(name).locked()
            ]
            if busy_names:
                logger.info(
                    f"数据库同步正在运行，跳过本次手动触发: {', '.join(busy_names)}"
                )
                return False, {}
            return True, await self._sync_all(
                github_token=github_token,
                trigger_remote_build=trigger_remote_build,
                force_remote_build=force_remote_build,
            )

    def load_cached_database(self, name: str) -> bool:
        entry = self.registered_syncs.get(name)
        if entry is None or not entry.local_path or not Path(entry.local_path).exists():
            return False
        try:
            self.databases.load_from_file(name, entry.local_path)
            logger.info(f"已从本地缓存加载数据库 '{name}': {entry.local_path}")
        except (OSError, ValueError):
            logger.exception(f"数据库 '{name}' 本地缓存加载失败: {entry.local_path}")
            return False
        return True

    def _prepare_remote_database(self, name: str) -> None:
        if name in self.prepared_databases:
            return
        self.databases.register(name)
        self.prepared_databases.add(name)

    def _prepare_local_database(self, name: str, file_path: str) -> None:
        if name in self.prepared_databases:
            return
        if not Path(file_path).exists():
            logger.warning(f"本地文件 '{file_path}' 不存在，跳过注册 {name}")
            return
        self.databases.register(name)
        self.databases.load_from_file(name, file_path)
        self.prepared_databases.add(name)
        logger.info(f"已从本地文件 '{file_path}' 加载数据库 '{name}'（无自动同步）")

    def format_remote_build_failures(self, failed_names: list[str]) -> str:
        return sync_formatting.format_remote_build_failures(
            failed_names,
            self.remote_build_results,
        )

    def format_local_versions(self, names: tuple[str, ...]) -> str:
        versions: dict[str, VersionInfo | None] = {}
        for name in names:
            entry = self.registered_syncs.get(name)
            local_path = entry.local_path if entry is not None else None
            if local_path is None or not Path(local_path).exists():
                versions[name] = None
                continue
            versions[name] = VersionInfo(
                fingerprint=self.fingerprints.get(name),
                timestamp=_file_timestamp(local_path),
            )
        return sync_formatting.format_local_versions(versions)

    def format_sync_statuses(self, results: dict[str, bool]) -> str:
        return sync_formatting.format_sync_statuses(results, self.last_sync_statuses)

    def format_sync_result_notice(
        self,
        results: dict[str, bool],
        *,
        title_prefix: str = "数据更新",
    ) -> str:
        return sync_formatting.format_sync_result_notice(
            results,
            sync_statuses=self.last_sync_statuses,
            remote_build_results=self.remote_build_results,
            title_prefix=title_prefix,
        )

    def skipped_names(self, results: dict[str, bool]) -> list[str]:
        return [
            name
            for name, ok in results.items()
            if ok and self.last_sync_statuses.get(name, SyncStatus(ok=True)).skipped
        ]

    def _lock(self, name: str) -> asyncio.Lock:
        return self._sync_locks.setdefault(name, asyncio.Lock())

    @staticmethod
    def _fingerprint_getter(url: str) -> GetFingerprintFn | None:
        if not url:
            return None

        async def get_fingerprint(client: httpx.AsyncClient) -> str:
            return (await client.get(url)).text

        return get_fingerprint

    def _load_matching_local_cache(
        self,
        name: str,
        entry: SyncEntry,
        local: VersionInfo,
        remote: VersionInfo,
        fingerprint: str | None,
    ) -> bool:
        if (
            fingerprint is None
            or local.fingerprint is None
            or fingerprint != local.fingerprint
            or not entry.local_path
        ):
            return False
        logger.info(
            f"数据库 '{name}' 本地缓存已是最新 ({fingerprint[:12]})，跳过下载"
        )
        self.databases.load_from_file(name, entry.local_path)
        self.fingerprints[name] = fingerprint
        self.last_sync_statuses[name] = SyncStatus(
            ok=True,
            skipped=True,
            local_before=local,
            remote=remote,
            message="本地与远端一致，无需更新",
        )
        return True

    async def _save_local_cache(
        self,
        name: str,
        entry: SyncEntry,
        content: bytes,
        local: VersionInfo,
    ) -> tuple[bool, datetime | None]:
        if not entry.local_path:
            return True, local.timestamp
        try:
            await to_thread.run_sync(_write_bytes_atomic, entry.local_path, content)
            return True, _file_timestamp(entry.local_path)
        except OSError:
            logger.exception(
                f"数据库 '{name}' 本地缓存写入失败: {entry.local_path}"
            )
            return False, local.timestamp

    async def _sync_all(
        self,
        *,
        github_token: str,
        trigger_remote_build: bool,
        force_remote_build: bool,
    ) -> dict[str, bool]:
        results: dict[str, bool] = {}
        if trigger_remote_build:
            self.remote_build_results.clear()
        for name, entry in self.registered_syncs.items():
            if trigger_remote_build and not await self._run_remote_build(
                name,
                entry,
                github_token,
                force=force_remote_build,
            ):
                results[name] = False
                continue
            results[name] = await self.sync_database(name)
        return results

    async def _run_remote_build(
        self,
        name: str,
        entry: SyncEntry,
        github_token: str,
        *,
        force: bool,
    ) -> bool:
        token = github_token.strip()
        return await sync_remote_build.run_remote_build(
            name=name,
            config=entry.remote_build,
            token=token,
            results=self.remote_build_results,
            trigger_workflow=lambda step: trigger_and_wait_workflow(step, token=token),
            force=force,
        )

    def _fail(
        self,
        name: str,
        local: VersionInfo,
        remote: VersionInfo,
        message: str,
    ) -> bool:
        self.last_sync_statuses[name] = SyncStatus(
            ok=False,
            local_before=local,
            remote=remote,
            message=message,
        )
        return False
