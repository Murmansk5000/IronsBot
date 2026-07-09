# SPDX-License-Identifier: MIT
import asyncio
import os
import tempfile
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import httpx
from anyio import Path as AsyncPath
from anyio import to_thread
from nonebot import on_message
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

from ironsbot.config import load_secrets_config
from ironsbot.config.models.runtime import RemoteBuildConfig
from ironsbot.integrations.db_sync.github_actions import (
    WorkflowRunResult,
    trigger_and_wait_workflow,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging.text import normalize_command_text
from ironsbot.utils.rule import no_reply

from . import formatting as sync_formatting
from . import remote_build as sync_remote_build
from .manager import db_manager
from .manual import ManualSyncContext, handle_manual_sync
from .storage import (
    _fetch_remote_timestamp,
    _file_timestamp,
    _fingerprint_content,
    _fingerprint_file,
    _normalize_fingerprint,
    _write_bytes_atomic,
)

GetFingerprintFn = Callable[[httpx.AsyncClient], Awaitable[str]]


class _SyncEntry(NamedTuple):
    sync_url: str
    sync_interval_minutes: int
    get_fingerprint: GetFingerprintFn | None = None
    local_path: str | None = None
    remote_build: RemoteBuildConfig | None = None


class _VersionInfo(NamedTuple):
    fingerprint: str | None = None
    timestamp: datetime | None = None


class _SyncStatus(NamedTuple):
    ok: bool
    skipped: bool = False
    local_before: _VersionInfo = _VersionInfo()
    remote: _VersionInfo = _VersionInfo()
    message: str = ""


_sync_locks: dict[str, asyncio.Lock] = {}
_sync_all_lock = asyncio.Lock()
_registered_syncs: dict[str, _SyncEntry] = {}
_registered_local_databases: dict[str, str] = {}
_prepared_databases: set[str] = set()
_fingerprints: dict[str, str] = {}
_last_sync_statuses: dict[str, _SyncStatus] = {}
_remote_build_results: dict[str, WorkflowRunResult] = {}
MANUAL_SYNC_COMMANDS = ("更新数据", "数据更新")
ADMIN_COMMAND_PREFIX = "/"


NORMALIZED_MANUAL_SYNC_COMMANDS = {
    normalize_command_text(command)
    for command in MANUAL_SYNC_COMMANDS
}


async def _is_manual_sync_command(event: Event) -> bool:
    text = event.get_plaintext().strip()
    if not text.startswith(ADMIN_COMMAND_PREFIX):
        return False

    command = normalize_command_text(text[len(ADMIN_COMMAND_PREFIX) :])
    return command in NORMALIZED_MANUAL_SYNC_COMMANDS


manual_sync_matcher = on_message(
    rule=Rule(_is_manual_sync_command) & no_reply(),
    permission=SUPERUSER,
    priority=get_matcher_priority("db_sync", 5),
    block=True,
)


def _get_lock(name: str) -> asyncio.Lock:
    if name not in _sync_locks:
        _sync_locks[name] = asyncio.Lock()
    return _sync_locks[name]


def is_sync_running() -> bool:
    return _sync_all_lock.locked() or any(
        _get_lock(name).locked()
        for name in _registered_syncs
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
    """登记一个从远程同步的内存数据库。供其他插件在模块级代码中调用。

    该函数只记录同步源；内存引擎、定时任务和启动同步会在 runtime setup
    安装的启动生命周期中完成。

    若提供 ``get_fingerprint``，每次同步前会先调用该函数获取远程指纹，
    与上次成功同步后的指纹对比；若相同则跳过下载。
    """
    if name in _registered_syncs or name in _registered_local_databases:
        logger.warning(f"数据库 '{name}' 已注册，跳过重复注册")
        return

    _registered_syncs[name] = _SyncEntry(
        sync_url,
        sync_interval_minutes,
        get_fingerprint,
        local_path,
        remote_build,
    )
    logger.debug(f"已登记远程同步数据库 '{name}'")


def register_local_database(name: str, *, file_path: str) -> None:
    """注册一个从本地文件加载的只读内存数据库，不设置自动同步。"""
    if name in _registered_syncs or name in _registered_local_databases:
        logger.warning(f"数据库 '{name}' 已注册，跳过重复注册")
        return

    _registered_local_databases[name] = file_path
    logger.debug(f"已登记本地数据库 '{name}': {file_path}")


async def sync_database(name: str) -> bool:  # noqa: C901, PLR0911, PLR0912, PLR0915
    """从远程 URL 下载 SQLite 数据库并导入到内存中。

    若注册时提供了 ``get_fingerprint``，会先获取远程指纹并与上次成功同步
    的指纹对比；相同则跳过下载。指纹仅在同步成功后更新。
    """
    entry = _registered_syncs.get(name)
    if not entry:
        return False

    async with _get_lock(name):
        local_before = _VersionInfo(
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
        remote = _VersionInfo()
        fd, tmp_name = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        tmp_path = AsyncPath(tmp_name)

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
                        logger.opt(exception=True).warning(
                            f"获取数据库 '{name}' 指纹失败，将继续执行同步"
                        )

                remote = _VersionInfo(
                    fingerprint=fingerprint,
                    timestamp=await _fetch_remote_timestamp(client, entry.sync_url),
                )

                if (
                    fingerprint is not None
                    and local_before.fingerprint is not None
                    and fingerprint == local_before.fingerprint
                    and entry.local_path
                ):
                    logger.info(
                        f"数据库 '{name}' 本地缓存已是最新 "
                        f"({fingerprint[:12]})，跳过下载"
                    )
                    db_manager.load_from_file(name, entry.local_path)
                    _fingerprints[name] = fingerprint
                    _last_sync_statuses[name] = _SyncStatus(
                        ok=True,
                        skipped=True,
                        local_before=local_before,
                        remote=remote,
                        message="本地与远端一致，无需更新",
                    )
                    return True

                if (
                    fingerprint is not None
                    and fingerprint == _fingerprints.get(name)
                    and not entry.local_path
                ):
                    logger.debug(
                        f"数据库 '{name}' 指纹未变化"
                        f" ({fingerprint})，跳过同步"
                    )
                    _last_sync_statuses[name] = _SyncStatus(
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
            await tmp_path.write_bytes(content_bytes)
            db_manager.load_from_file(name, str(tmp_path))

            cache_saved = True
            if entry.local_path:
                try:
                    await to_thread.run_sync(
                        _write_bytes_atomic,
                        entry.local_path,
                        content_bytes,
                    )
                    local_timestamp_after = _file_timestamp(entry.local_path)
                except OSError:
                    cache_saved = False
                    local_timestamp_after = local_before.timestamp
                    logger.exception(
                        f"数据库 '{name}' 本地缓存写入失败: {entry.local_path}"
                    )
            else:
                local_timestamp_after = local_before.timestamp

            if fingerprint is not None:
                _fingerprints[name] = fingerprint
            else:
                _fingerprints[name] = content_fingerprint

            if remote.fingerprint is None:
                remote = _VersionInfo(
                    fingerprint=content_fingerprint,
                    timestamp=remote.timestamp,
                )

            size_mb = len(content) / (1024 * 1024)
            logger.info(f"数据库 '{name}' 已同步到内存，源文件大小: {size_mb:.2f} MB")
            _last_sync_statuses[name] = _SyncStatus(
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

        except httpx.HTTPStatusError as e:
            logger.warning(
                f"数据库 '{name}' 同步失败（HTTP {e.response.status_code}）："
                f"{e.request.url}"
            )
            _last_sync_statuses[name] = _SyncStatus(
                ok=False,
                local_before=local_before,
                remote=remote,
                message=f"HTTP {e.response.status_code}",
            )
            return False
        except httpx.TransportError as e:
            logger.warning(
                f"数据库 '{name}' 同步失败（网络连接错误）："
                f"{type(e).__name__}: {e}"
            )
            _last_sync_statuses[name] = _SyncStatus(
                ok=False,
                local_before=local_before,
                remote=remote,
                message=f"{type(e).__name__}: {e}",
            )
            return False
        except httpx.HTTPError as e:
            logger.warning(
                f"数据库 '{name}' 同步失败（HTTP 客户端错误）："
                f"{type(e).__name__}: {e}"
            )
            _last_sync_statuses[name] = _SyncStatus(
                ok=False,
                local_before=local_before,
                remote=remote,
                message=f"{type(e).__name__}: {e}",
            )
            return False
        except (OSError, ValueError):
            logger.exception(f"数据库 '{name}' 同步失败（文件或导入错误）")
            _last_sync_statuses[name] = _SyncStatus(
                ok=False,
                local_before=local_before,
                remote=remote,
                message="文件或导入错误",
            )
            return False
        else:
            return cache_saved
        finally:
            await tmp_path.unlink(missing_ok=True)


async def run_sync_database(name: str) -> bool:
    if _sync_all_lock.locked():
        logger.info(f"数据库全量同步正在运行，跳过 '{name}' 本次定时同步")
        return False

    if _get_lock(name).locked():
        logger.info(f"数据库 '{name}' 正在同步，跳过本次触发")
        return False

    return await sync_database(name)


def _remote_build_names() -> list[str]:
    return [
        name
        for name, entry in _registered_syncs.items()
        if entry.remote_build is not None and entry.remote_build.enabled
    ]


async def _run_remote_build(name: str, entry: _SyncEntry) -> bool:
    token = load_secrets_config().github_workflow_token.strip()
    return await sync_remote_build.run_remote_build(
        name=name,
        config=entry.remote_build,
        token=token,
        results=_remote_build_results,
        trigger_workflow=lambda step: trigger_and_wait_workflow(step, token=token),
    )


async def sync_all_databases(*, trigger_remote_build: bool = False) -> dict[str, bool]:
    results: dict[str, bool] = {}
    if trigger_remote_build:
        _remote_build_results.clear()

    for name, entry in _registered_syncs.items():
        if trigger_remote_build and not await _run_remote_build(name, entry):
            results[name] = False
            continue
        results[name] = await sync_database(name)
    return results


async def run_sync_all_databases(
    *,
    trigger_remote_build: bool = False,
) -> tuple[bool, dict[str, bool]]:
    if _sync_all_lock.locked():
        logger.info("数据库全量同步正在运行，跳过本次手动触发")
        return False, {}

    async with _sync_all_lock:
        busy_names = [
            name for name in _registered_syncs
            if _get_lock(name).locked()
        ]
        if busy_names:
            logger.info(
                "数据库同步正在运行，跳过本次手动触发: "
                f"{', '.join(busy_names)}"
            )
            return False, {}

        return True, await sync_all_databases(
            trigger_remote_build=trigger_remote_build
        )


def load_cached_database(name: str) -> bool:
    entry = _registered_syncs.get(name)
    if not entry or not entry.local_path or not Path(entry.local_path).exists():
        return False

    try:
        db_manager.load_from_file(name, entry.local_path)
        logger.info(f"已从本地缓存加载数据库 '{name}': {entry.local_path}")
    except (OSError, ValueError):
        logger.exception(f"数据库 '{name}' 本地缓存加载失败: {entry.local_path}")
        return False
    else:
        return True


def _prepare_remote_database(name: str) -> None:
    if name in _prepared_databases:
        return

    db_manager.register(name)
    _prepared_databases.add(name)


def _prepare_local_database(name: str, file_path: str) -> None:
    if name in _prepared_databases:
        return

    if not Path(file_path).exists():
        logger.warning(f"本地文件 '{file_path}' 不存在，跳过注册 {name}")
        return

    db_manager.register(name)
    db_manager.load_from_file(name, file_path)
    _prepared_databases.add(name)
    logger.info(f"已从本地文件 '{file_path}' 加载数据库 '{name}'（无自动同步）")


@manual_sync_matcher.handle()
async def _handle_manual_sync(matcher: Matcher, event: MessageEvent) -> None:
    await handle_manual_sync(
        matcher,
        event,
        context=ManualSyncContext(
            registered_syncs=_registered_syncs,
            last_sync_statuses=_last_sync_statuses,
            default_sync_status=_SyncStatus(ok=True),
            is_sync_running=is_sync_running,
            remote_build_names=_remote_build_names,
            run_sync_all_databases=run_sync_all_databases,
            format_sync_statuses=_format_sync_statuses,
            format_remote_build_failures=_format_remote_build_failures,
        ),
    )


def _format_remote_build_failures(failed_names: list[str]) -> str:
    return sync_formatting.format_remote_build_failures(
        failed_names,
        _remote_build_results,
    )


def _format_timestamp(value: datetime | None) -> str:
    return sync_formatting.format_timestamp(value)


def _format_fingerprint(value: str | None) -> str:
    return sync_formatting.format_fingerprint(value)


def _format_sync_statuses(results: dict[str, bool]) -> str:
    return sync_formatting.format_sync_statuses(
        results,
        _last_sync_statuses,
    )


def format_sync_result_notice(
    results: dict[str, bool],
    *,
    title_prefix: str = "数据更新",
) -> str:
    return sync_formatting.format_sync_result_notice(
        results,
        sync_statuses=_last_sync_statuses,
        remote_build_results=_remote_build_results,
        title_prefix=title_prefix,
    )
