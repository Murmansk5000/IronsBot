# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
from pathlib import Path

from nonebot import get_driver, require
from nonebot.log import logger
from seerapi_models import ApiMetadataORM
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from ..config import plugin_config

require("ironsbot.plugins.db_sync")
require("nonebot_plugin_localstore")

config = get_driver().config

import nonebot_plugin_localstore as store

from ironsbot.plugins.db_sync.manager import db_manager

CACHE_DIR: Path = plugin_config.render_cache_dir or store.get_plugin_cache_dir()


_SEERAPI_DB = "seerapi"
_UNKNOWN_VERSION = "unknown"


class RenderCache:
    """渲染结果的磁盘缓存，绑定 seerapi 数据库版本号。

    缓存文件名格式: {category}_{content_key}_{db_version_hash}.png
    当数据库版本变化时，旧版本的缓存不再命中，会在清理时被移除。
    """

    def __init__(self, cache_dir: Path, max_size_bytes: int) -> None:
        self._cache_dir = cache_dir
        self._max_size_bytes = max_size_bytes
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_db_version(self) -> str:
        engine = db_manager.get_engine(_SEERAPI_DB)
        if engine is None:
            return _UNKNOWN_VERSION
        try:
            with SQLModelSession(engine) as session:
                obj = session.exec(select(ApiMetadataORM)).first()
                if obj is not None:
                    return obj.generate_time.isoformat()
        except Exception:
            logger.opt(exception=True).debug("查询数据库版本失败")
        return _UNKNOWN_VERSION

    @staticmethod
    def _version_hash(version: str) -> str:
        return hashlib.sha256(version.encode()).hexdigest()[:12]

    def _build_filename(self, category: str, content_key: str, ver_hash: str) -> str:
        return f"{category}_{content_key}_{ver_hash}.png"

    def _build_path(self, category: str, content_key: str, ver_hash: str) -> Path:
        return self._cache_dir / self._build_filename(category, content_key, ver_hash)

    def get(self, category: str, content_key: str) -> bytes | None:
        """查找缓存，命中返回 PNG bytes，未命中返回 None。"""
        version = self._get_db_version()
        if version == _UNKNOWN_VERSION:
            return None
        ver_hash = self._version_hash(version)
        path = self._build_path(category, content_key, ver_hash)
        if path.exists():
            logger.debug(f"渲染缓存命中: {path.name}")
            return path.read_bytes()
        return None

    def put(self, category: str, content_key: str, data: bytes) -> None:
        """写入缓存文件，然后触发大小检查与清理。"""
        version = self._get_db_version()
        if version == _UNKNOWN_VERSION:
            return
        ver_hash = self._version_hash(version)
        path = self._build_path(category, content_key, ver_hash)
        path.write_bytes(data)
        logger.debug(f"渲染缓存写入: {path.name} ({len(data)} bytes)")
        self.cleanup()

    def cleanup(self) -> None:
        """检查总缓存大小，超限时按修改时间从旧到新删除文件。"""
        files = [f for f in self._cache_dir.iterdir() if f.is_file()]
        total_size = sum(f.stat().st_size for f in files)
        if total_size <= self._max_size_bytes:
            return

        files.sort(key=lambda f: f.stat().st_mtime)
        removed = 0
        for f in files:
            if total_size <= self._max_size_bytes:
                break
            size = f.stat().st_size
            f.unlink(missing_ok=True)
            total_size -= size
            removed += 1

        if removed:
            logger.info(f"渲染缓存清理: 删除 {removed} 个文件")

    def clear(self) -> None:
        """删除缓存目录下的所有缓存文件。"""
        files = [f for f in self._cache_dir.iterdir() if f.is_file()]
        for f in files:
            f.unlink(missing_ok=True)
        if files:
            logger.info(f"渲染缓存清空: 删除 {len(files)} 个文件")

    @property
    def total_size(self) -> int:
        """当前缓存目录总大小（bytes）。"""
        return sum(f.stat().st_size for f in self._cache_dir.iterdir() if f.is_file())


render_cache: RenderCache = RenderCache(
    cache_dir=CACHE_DIR,
    max_size_bytes=plugin_config.render_cache_max_size_mb * 1024 * 1024,
)

if plugin_config.render_cache_clear_on_startup:
    render_cache.clear()
