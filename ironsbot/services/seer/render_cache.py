# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from nonebot.log import logger
from seerapi_models import ApiMetadataORM
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from ironsbot.config import get_app_config
from ironsbot.integrations.db_registry import db_manager

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.config.models.seer import RenderConfig

_SEERAPI_DB = "seerapi"
UNKNOWN_RENDER_CACHE_VERSION = "unknown"


def get_render_config() -> RenderConfig:
    return get_app_config().seer.render


def get_render_cache_dir() -> Path:
    cache_dir = get_render_config().cache_dir
    if cache_dir is not None:
        return cache_dir

    from nonebot_plugin_localstore import get_plugin_cache_dir

    return get_plugin_cache_dir()


def get_render_cache_max_size_bytes() -> int:
    return get_render_config().cache_max_size_mb * 1024 * 1024


def get_seerapi_db_version() -> str:
    engine = db_manager.get_engine(_SEERAPI_DB)
    if engine is None:
        return UNKNOWN_RENDER_CACHE_VERSION
    try:
        with SQLModelSession(engine) as session:
            obj = session.exec(select(ApiMetadataORM)).first()
            if obj is not None:
                return obj.generate_time.isoformat()
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).debug("查询数据库版本失败")
    return UNKNOWN_RENDER_CACHE_VERSION


class RenderCache:
    """Disk cache for rendered Seer images, scoped by the seerapi data version."""

    def __init__(
        self,
        *,
        cache_dir_getter: Callable[[], Path] = get_render_cache_dir,
        max_size_bytes_getter: Callable[[], int] = get_render_cache_max_size_bytes,
        db_version_getter: Callable[[], str] = get_seerapi_db_version,
    ) -> None:
        self._cache_dir_getter = cache_dir_getter
        self._max_size_bytes_getter = max_size_bytes_getter
        self._db_version_getter = db_version_getter

    @property
    def _cache_dir(self) -> Path:
        return self._cache_dir_getter()

    @property
    def _max_size_bytes(self) -> int:
        return self._max_size_bytes_getter()

    def _ensure_cache_dir(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_db_version(self) -> str:
        return self._db_version_getter()

    @staticmethod
    def _version_hash(version: str) -> str:
        return hashlib.sha256(version.encode()).hexdigest()[:12]

    def _build_filename(self, category: str, content_key: str, ver_hash: str) -> str:
        return f"{category}_{content_key}_{ver_hash}.png"

    def _build_path(self, category: str, content_key: str, ver_hash: str) -> Path:
        return self._cache_dir / self._build_filename(category, content_key, ver_hash)

    def get(self, category: str, content_key: str) -> bytes | None:
        version = self._get_db_version()
        if version == UNKNOWN_RENDER_CACHE_VERSION:
            return None
        ver_hash = self._version_hash(version)
        path = self._build_path(category, content_key, ver_hash)
        if path.exists():
            logger.debug(f"渲染缓存命中: {path.name}")
            return path.read_bytes()
        return None

    def put(self, category: str, content_key: str, data: bytes) -> None:
        version = self._get_db_version()
        if version == UNKNOWN_RENDER_CACHE_VERSION:
            return
        self._ensure_cache_dir()
        ver_hash = self._version_hash(version)
        path = self._build_path(category, content_key, ver_hash)
        path.write_bytes(data)
        logger.debug(f"渲染缓存写入: {path.name} ({len(data)} bytes)")
        self.cleanup()

    def cleanup(self) -> None:
        if not self._cache_dir.exists():
            return
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

    @property
    def total_size(self) -> int:
        if not self._cache_dir.exists():
            return 0
        return sum(f.stat().st_size for f in self._cache_dir.iterdir() if f.is_file())


render_cache = RenderCache()


__all__ = [
    "UNKNOWN_RENDER_CACHE_VERSION",
    "RenderCache",
    "get_render_cache_dir",
    "get_render_cache_max_size_bytes",
    "get_render_config",
    "get_seerapi_db_version",
    "render_cache",
]
