# SPDX-License-Identifier: MIT
import asyncio
import os
import tempfile
from collections.abc import Awaitable, Callable
from typing import Literal, NamedTuple

import httpx
from anyio import Path
from nonebot import get_driver, require
from nonebot.log import logger

require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler

from .manager import db_manager

GetFingerprintFn = Callable[[httpx.AsyncClient], Awaitable[str]]
#: 数据库同步成功（返回 "updated"）后的回调
SyncUpdatedHook = Callable[[], Awaitable[None]]


class _SyncEntry(NamedTuple):
    sync_url: str
    sync_interval_minutes: int
    get_fingerprint: GetFingerprintFn | None = None


_driver = get_driver()
_sync_locks: dict[str, asyncio.Lock] = {}
_registered_syncs: dict[str, _SyncEntry] = {}
_local_databases: set[str] = set()
_fingerprints: dict[str, str] = {}
_update_hooks: dict[str, list[SyncUpdatedHook]] = {}


def register_update_hook(name: str, hook: SyncUpdatedHook) -> None:
    """注册数据库同步成功（返回 ``"updated"``）后的回调。

    供其他插件在数据更新后执行后续动作（如推送更新通知）。
    回调在 ``sync_database`` 成功导入新数据后、返回 ``"updated"`` 前依次执行；
    首次同步（启动时）成功也会触发。

    Args:
        name: 数据库名称
        hook: 异步回调，无参数
    """
    _update_hooks.setdefault(name, []).append(hook)


async def _run_one_hook(name: str, hook: SyncUpdatedHook) -> None:
    try:
        await hook()
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning(f"数据库 '{name}' 更新回调执行失败")


async def _run_update_hooks(name: str) -> None:
    for hook in _update_hooks.get(name, []):
        await _run_one_hook(name, hook)


def _get_lock(name: str) -> asyncio.Lock:
    if name not in _sync_locks:
        _sync_locks[name] = asyncio.Lock()
    return _sync_locks[name]


def register_database(
    name: str,
    *,
    sync_url: str,
    sync_interval_minutes: int = 60,
    get_fingerprint: GetFingerprintFn | None = None,
) -> None:
    """注册一个从远程同步的内存数据库。供其他插件在模块级代码中调用。

    该函数会：
    1. 在 db_manager 中注册内存引擎
    2. 添加定时同步任务
    3. 在启动时自动执行首次同步

    若提供 ``get_fingerprint``，每次同步前会先调用该函数获取远程指纹，
    与上次成功同步后的指纹对比；若相同则跳过下载。
    """
    if name in _registered_syncs or name in _local_databases:
        logger.warning(f"数据库 '{name}' 已注册，跳过重复注册")
        return

    db_manager.register(name)
    _registered_syncs[name] = _SyncEntry(
        sync_url, sync_interval_minutes, get_fingerprint
    )

    scheduler.add_job(
        sync_database,
        "interval",
        args=[name],
        minutes=sync_interval_minutes,
        id=f"db_sync_{name}",
        replace_existing=True,
    )
    logger.debug(f"已注册数据库 '{name}'，同步间隔: {sync_interval_minutes} 分钟")


def register_local_database(name: str, *, file_path: str) -> None:
    """注册一个从本地文件加载的只读内存数据库，不设置自动同步。"""
    if name in _registered_syncs or name in _local_databases:
        logger.warning(f"数据库 '{name}' 已注册，跳过重复注册")
        return

    # 同步上下文无法 await，anyio.Path.exists() 为协程方法，故使用 os.path.exists
    if not os.path.exists(file_path):  # noqa: PTH110
        logger.warning(f"本地文件 '{file_path}' 不存在，跳过注册 {name}")
        return

    db_manager.register(name)
    db_manager.load_from_file(name, file_path)
    _local_databases.add(name)
    logger.info(f"已从本地文件 '{file_path}' 加载数据库 '{name}'（无自动同步）")


SyncResult = Literal["updated", "skipped", "failed"]


async def sync_database(name: str) -> SyncResult | None:
    """从远程 URL 下载 SQLite 数据库并导入到内存中。

    若注册时提供了 ``get_fingerprint``，会先获取远程指纹并与上次成功同步
    的指纹对比；相同则跳过下载。指纹仅在同步成功后更新。

    返回同步结果状态：
    - ``"updated"``：成功更新到内存
    - ``"skipped"``：指纹未变化，跳过同步
    - ``"failed"``：同步或导入失败
    - ``None``：未注册的同步数据库
    """
    entry = _registered_syncs.get(name)
    if not entry:
        return None

    async with _get_lock(name):
        fd, tmp_name = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        tmp_path = Path(tmp_name)

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, read=120.0),
            ) as client:
                fingerprint: str | None = None
                if entry.get_fingerprint is not None:
                    try:
                        fingerprint = await entry.get_fingerprint(client)
                        if fingerprint == _fingerprints.get(name):
                            logger.debug(
                                f"数据库 '{name}' 指纹未变化 ({fingerprint})，跳过同步"
                            )
                            return "skipped"
                    except Exception:  # noqa: BLE001
                        logger.opt(exception=True).warning(
                            f"获取数据库 '{name}' 指纹失败，将继续执行同步"
                        )

                logger.info(f"开始从 {entry.sync_url} 同步数据库 '{name}'...")
                content = bytearray()
                async with client.stream("GET", entry.sync_url) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        content.extend(chunk)

            await tmp_path.write_bytes(bytes(content))
            db_manager.load_from_file(name, str(tmp_path))

            if fingerprint is not None:
                _fingerprints[name] = fingerprint

            size_mb = len(content) / (1024 * 1024)
            logger.info(f"数据库 '{name}' 已同步到内存，源文件大小: {size_mb:.2f} MB")

        except httpx.HTTPError:
            logger.exception(f"数据库 '{name}' 同步失败（HTTP 错误）")
            return "failed"
        except (OSError, ValueError):
            logger.exception(f"数据库 '{name}' 同步失败（文件或导入错误）")
            return "failed"
        finally:
            await tmp_path.unlink(missing_ok=True)

        await _run_update_hooks(name)
        return "updated"


def get_registered_sync_names() -> list[str]:
    """获取所有已注册的远程同步数据库名称。"""
    return list(_registered_syncs.keys())


@_driver.on_startup
async def _on_startup() -> None:
    if not _registered_syncs:
        logger.debug("无已注册的同步数据库，db_sync 插件未激活")
        return

    for name, entry in _registered_syncs.items():
        logger.info(
            f"数据库 '{name}' 同步已启动，同步间隔: {entry.sync_interval_minutes} 分钟"
        )
        await sync_database(name)
