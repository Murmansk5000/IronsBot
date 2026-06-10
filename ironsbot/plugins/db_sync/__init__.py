# SPDX-License-Identifier: MIT
import asyncio
import os
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import NamedTuple

import httpx
from anyio import Path as AsyncPath
from anyio import to_thread
from nonebot import get_driver, on_message, require
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule

require("nonebot_plugin_apscheduler")

from nonebot_plugin_apscheduler import scheduler

from ironsbot.custom_plugins.message_actions import finish_event_reply, send_event_reply
from ironsbot.utils.rule import no_reply

from .config import plugin_config
from .manager import db_manager

GetFingerprintFn = Callable[[httpx.AsyncClient], Awaitable[str]]


class _SyncEntry(NamedTuple):
    sync_url: str
    sync_interval_minutes: int
    get_fingerprint: GetFingerprintFn | None = None
    local_path: str | None = None


_driver = get_driver()
_sync_locks: dict[str, asyncio.Lock] = {}
_sync_all_lock = asyncio.Lock()
_registered_syncs: dict[str, _SyncEntry] = {}
_local_databases: set[str] = set()
_fingerprints: dict[str, str] = {}
MANUAL_SYNC_COMMANDS = ("更新数据", "数据更新")
ADMIN_COMMAND_PREFIX = "/"


def _normalize_command_text(text: str) -> str:
    return "".join(text.split()).lower()


NORMALIZED_MANUAL_SYNC_COMMANDS = {
    _normalize_command_text(command)
    for command in MANUAL_SYNC_COMMANDS
}


async def _is_manual_sync_command(event: Event) -> bool:
    text = event.get_plaintext().strip()
    if not text.startswith(ADMIN_COMMAND_PREFIX):
        return False

    command = _normalize_command_text(text[len(ADMIN_COMMAND_PREFIX) :])
    return command in NORMALIZED_MANUAL_SYNC_COMMANDS


manual_sync_matcher = on_message(
    rule=Rule(_is_manual_sync_command) & no_reply(),
    permission=SUPERUSER,
    priority=5,
    block=True,
)


def _get_lock(name: str) -> asyncio.Lock:
    if name not in _sync_locks:
        _sync_locks[name] = asyncio.Lock()
    return _sync_locks[name]


def _write_bytes_atomic(file_path: str, content: bytes) -> None:
    target_path = Path(file_path)
    parent = target_path.parent
    if parent != Path():
        parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = parent if parent != Path() else Path.cwd()
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(tmp_dir),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        tmp_path.replace(target_path)
    finally:
        with suppress(FileNotFoundError):
            tmp_path.unlink()


def is_sync_running() -> bool:
    return _sync_all_lock.locked() or any(
        _get_lock(name).locked()
        for name in _registered_syncs
    )


def register_database(
    name: str,
    *,
    sync_url: str,
    sync_interval_minutes: int = 60,
    get_fingerprint: GetFingerprintFn | None = None,
    local_path: str | None = None,
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
        sync_url, sync_interval_minutes, get_fingerprint, local_path
    )

    if plugin_config.data_sync_config.interval_enabled:
        scheduler.add_job(
            run_sync_database,
            "interval",
            args=[name],
            minutes=sync_interval_minutes,
            id=f"db_sync_{name}",
            replace_existing=True,
        )
        logger.debug(f"已注册数据库 '{name}'，同步间隔: {sync_interval_minutes} 分钟")
    else:
        logger.debug(f"已注册数据库 '{name}'，自动定时同步已关闭")


def register_local_database(name: str, *, file_path: str) -> None:
    """注册一个从本地文件加载的只读内存数据库，不设置自动同步。"""
    if name in _registered_syncs or name in _local_databases:
        logger.warning(f"数据库 '{name}' 已注册，跳过重复注册")
        return

    if not Path(file_path).exists():
        logger.warning(f"本地文件 '{file_path}' 不存在，跳过注册 {name}")
        return

    db_manager.register(name)
    db_manager.load_from_file(name, file_path)
    _local_databases.add(name)
    logger.info(f"已从本地文件 '{file_path}' 加载数据库 '{name}'（无自动同步）")


async def sync_database(name: str) -> bool:  # noqa: C901
    """从远程 URL 下载 SQLite 数据库并导入到内存中。

    若注册时提供了 ``get_fingerprint``，会先获取远程指纹并与上次成功同步
    的指纹对比；相同则跳过下载。指纹仅在同步成功后更新。
    """
    entry = _registered_syncs.get(name)
    if not entry:
        return False

    async with _get_lock(name):
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
                        fingerprint = await entry.get_fingerprint(client)
                        if fingerprint == _fingerprints.get(name):
                            logger.debug(
                                f"数据库 '{name}' 指纹未变化"
                                f" ({fingerprint})，跳过同步"
                            )
                            return True
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

            content_bytes = bytes(content)
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
                except OSError:
                    cache_saved = False
                    logger.exception(
                        f"数据库 '{name}' 本地缓存写入失败: {entry.local_path}"
                    )

            if fingerprint is not None:
                _fingerprints[name] = fingerprint

            size_mb = len(content) / (1024 * 1024)
            logger.info(f"数据库 '{name}' 已同步到内存，源文件大小: {size_mb:.2f} MB")

        except httpx.HTTPError:
            logger.exception(f"数据库 '{name}' 同步失败（HTTP 错误）")
            return False
        except (OSError, ValueError):
            logger.exception(f"数据库 '{name}' 同步失败（文件或导入错误）")
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


async def sync_all_databases() -> dict[str, bool]:
    results: dict[str, bool] = {}
    for name in _registered_syncs:
        results[name] = await sync_database(name)
    return results


async def run_sync_all_databases() -> tuple[bool, dict[str, bool]]:
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

        return True, await sync_all_databases()


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


@manual_sync_matcher.handle()
async def _handle_manual_sync(matcher: Matcher, event: MessageEvent) -> None:
    if not _registered_syncs:
        await finish_event_reply(matcher, event, "当前没有已注册的远程同步数据库。")

    if is_sync_running():
        await finish_event_reply(matcher, event, "⏳ 数据更新正在进行中，请稍后再试。")

    names = list(_registered_syncs)
    await send_event_reply(
        matcher,
        event,
        f"开始更新数据：{', '.join(names)}，请稍等。",
    )

    did_run, results = await run_sync_all_databases()

    if not did_run:
        await finish_event_reply(matcher, event, "⏳ 数据更新正在进行中，请稍后再试。")

    failed = [name for name, ok in results.items() if not ok]
    succeeded = [name for name, ok in results.items() if ok]

    if failed:
        await finish_event_reply(
            matcher,
            event,
            "数据更新完成，但有失败项。\n"
            f"成功：{', '.join(succeeded) if succeeded else '无'}\n"
            f"失败：{', '.join(failed)}\n"
            "请查看容器日志确认网络或下载错误。"
        )

    await finish_event_reply(matcher, event, f"数据更新完成：{', '.join(succeeded)}")


@_driver.on_startup
async def _on_startup() -> None:
    if not _registered_syncs:
        logger.debug("无已注册的同步数据库，db_sync 插件未激活")
        return

    for name, entry in _registered_syncs.items():
        logger.info(
            f"数据库 '{name}' 同步已启动，同步间隔: {entry.sync_interval_minutes} 分钟"
        )

    for name in _registered_syncs:
        load_cached_database(name)

    # Keep startup sync behind a switch to avoid slow container startup.
    if not plugin_config.data_sync_config.on_startup:
        logger.info("启动时数据库同步已关闭，可由超级管理员发送“/更新数据”手动同步")
        return

    async with _sync_all_lock:
        for name in _registered_syncs:
            await sync_database(name)
