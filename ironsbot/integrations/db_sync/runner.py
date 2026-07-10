# SPDX-License-Identifier: MIT
import os
import tempfile
from pathlib import Path

import httpx
from anyio import Path as AsyncPath
from anyio import to_thread
from nonebot.log import logger

from ironsbot.config.loader import load_secrets_config
from ironsbot.integrations.db_registry import db_manager
from ironsbot.integrations.db_sync.github_actions import trigger_and_wait_workflow

from . import formatting as sync_formatting
from . import remote_build as sync_remote_build
from . import state as sync_state
from .models import SyncEntry, SyncStatus, VersionInfo
from .storage import (
    _fetch_remote_timestamp,
    _file_timestamp,
    _fingerprint_content,
    _fingerprint_file,
    _normalize_fingerprint,
    _write_bytes_atomic,
)


async def sync_database(name: str) -> bool:  # noqa: C901, PLR0911, PLR0912, PLR0915
    """从远程 URL 下载 SQLite 数据库并导入到内存中。

    若注册时提供了 ``get_fingerprint``，会先获取远程指纹并与上次成功同步
    的指纹对比；相同则跳过下载。指纹仅在同步成功后更新。
    """
    entry = sync_state.registered_syncs.get(name)
    if not entry:
        return False

    async with sync_state.get_lock(name):
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

                remote = VersionInfo(
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
                    sync_state.fingerprints[name] = fingerprint
                    sync_state.last_sync_statuses[name] = SyncStatus(
                        ok=True,
                        skipped=True,
                        local_before=local_before,
                        remote=remote,
                        message="本地与远端一致，无需更新",
                    )
                    return True

                if (
                    fingerprint is not None
                    and fingerprint == sync_state.fingerprints.get(name)
                    and not entry.local_path
                ):
                    logger.debug(
                        f"数据库 '{name}' 指纹未变化"
                        f" ({fingerprint})，跳过同步"
                    )
                    sync_state.last_sync_statuses[name] = SyncStatus(
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
                sync_state.fingerprints[name] = fingerprint
            else:
                sync_state.fingerprints[name] = content_fingerprint

            if remote.fingerprint is None:
                remote = VersionInfo(
                    fingerprint=content_fingerprint,
                    timestamp=remote.timestamp,
                )

            size_mb = len(content) / (1024 * 1024)
            logger.info(f"数据库 '{name}' 已同步到内存，源文件大小: {size_mb:.2f} MB")
            sync_state.last_sync_statuses[name] = SyncStatus(
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
            sync_state.last_sync_statuses[name] = SyncStatus(
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
            sync_state.last_sync_statuses[name] = SyncStatus(
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
            sync_state.last_sync_statuses[name] = SyncStatus(
                ok=False,
                local_before=local_before,
                remote=remote,
                message=f"{type(e).__name__}: {e}",
            )
            return False
        except (OSError, ValueError):
            logger.exception(f"数据库 '{name}' 同步失败（文件或导入错误）")
            sync_state.last_sync_statuses[name] = SyncStatus(
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
    if sync_state.sync_all_lock.locked():
        logger.info(f"数据库全量同步正在运行，跳过 '{name}' 本次定时同步")
        return False

    if sync_state.get_lock(name).locked():
        logger.info(f"数据库 '{name}' 正在同步，跳过本次触发")
        return False

    return await sync_database(name)


def remote_build_names() -> list[str]:
    return [
        name
        for name, entry in sync_state.registered_syncs.items()
        if entry.remote_build is not None and entry.remote_build.enabled
    ]


async def _run_remote_build(
    name: str,
    entry: SyncEntry,
    *,
    force: bool = False,
) -> bool:
    token = load_secrets_config().github_workflow_token.strip()
    return await sync_remote_build.run_remote_build(
        name=name,
        config=entry.remote_build,
        token=token,
        results=sync_state.remote_build_results,
        trigger_workflow=lambda step: trigger_and_wait_workflow(step, token=token),
        force=force,
    )


async def sync_all_databases(
    *,
    trigger_remote_build: bool = False,
    force_remote_build: bool = False,
) -> dict[str, bool]:
    results: dict[str, bool] = {}
    if trigger_remote_build:
        sync_state.remote_build_results.clear()

    for name, entry in sync_state.registered_syncs.items():
        if trigger_remote_build and not await _run_remote_build(
            name,
            entry,
            force=force_remote_build,
        ):
            results[name] = False
            continue
        results[name] = await sync_database(name)
    return results


async def run_sync_all_databases(
    *,
    trigger_remote_build: bool = False,
    force_remote_build: bool = False,
) -> tuple[bool, dict[str, bool]]:
    if sync_state.sync_all_lock.locked():
        logger.info("数据库全量同步正在运行，跳过本次手动触发")
        return False, {}

    async with sync_state.sync_all_lock:
        busy_names = [
            name for name in sync_state.registered_syncs
            if sync_state.get_lock(name).locked()
        ]
        if busy_names:
            logger.info(
                "数据库同步正在运行，跳过本次手动触发: "
                f"{', '.join(busy_names)}"
            )
            return False, {}

        return True, await sync_all_databases(
            trigger_remote_build=trigger_remote_build,
            force_remote_build=force_remote_build,
        )


def load_cached_database(name: str) -> bool:
    entry = sync_state.registered_syncs.get(name)
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


def prepare_remote_database(name: str) -> None:
    if name in sync_state.prepared_databases:
        return

    db_manager.register(name)
    sync_state.prepared_databases.add(name)


def prepare_local_database(name: str, file_path: str) -> None:
    if name in sync_state.prepared_databases:
        return

    if not Path(file_path).exists():
        logger.warning(f"本地文件 '{file_path}' 不存在，跳过注册 {name}")
        return

    db_manager.register(name)
    db_manager.load_from_file(name, file_path)
    sync_state.prepared_databases.add(name)
    logger.info(f"已从本地文件 '{file_path}' 加载数据库 '{name}'（无自动同步）")


def format_remote_build_failures(failed_names: list[str]) -> str:
    return sync_formatting.format_remote_build_failures(
        failed_names,
        sync_state.remote_build_results,
    )


def format_sync_statuses(results: dict[str, bool]) -> str:
    return sync_formatting.format_sync_statuses(
        results,
        sync_state.last_sync_statuses,
    )


def format_sync_result_notice(
    results: dict[str, bool],
    *,
    title_prefix: str = "数据更新",
) -> str:
    return sync_formatting.format_sync_result_notice(
        results,
        sync_statuses=sync_state.last_sync_statuses,
        remote_build_results=sync_state.remote_build_results,
        title_prefix=title_prefix,
    )
