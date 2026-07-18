# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from nonebot.log import logger
from seerapi_models import ApiMetadataORM
from sqlmodel import Session as SQLModelSession
from sqlmodel import select

from ironsbot.integrations.db_registry import db_manager

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_SEERAPI_DB = "seerapi"
UNKNOWN_RENDER_CACHE_VERSION = "unknown"


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
        cache_dir: Path,
        max_size_bytes: int,
        *,
        db_version_getter: Callable[[], str] = get_seerapi_db_version,
    ) -> None:
        self._cache_dir = cache_dir
        self._max_size_bytes = max_size_bytes
        self._db_version_getter = db_version_getter

    def _ensure_cache_dir(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _version_hash(version: str) -> str:
        return hashlib.sha256(version.encode()).hexdigest()[:12]

    def _build_filename(self, category: str, content_key: str, ver_hash: str) -> str:
        return f"{category}_{content_key}_{ver_hash}.png"

    def _build_path(self, category: str, content_key: str, ver_hash: str) -> Path:
        return self._cache_dir / self._build_filename(category, content_key, ver_hash)

    def get(self, category: str, content_key: str) -> bytes | None:
        version = self._db_version_getter()
        if version == UNKNOWN_RENDER_CACHE_VERSION:
            return None
        ver_hash = self._version_hash(version)
        path = self._build_path(category, content_key, ver_hash)
        if path.exists():
            logger.debug(f"渲染缓存命中: {path.name}")
            return path.read_bytes()
        return None

    def put(self, category: str, content_key: str, data: bytes) -> None:
        version = self._db_version_getter()
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

__all__ = [
    "UNKNOWN_RENDER_CACHE_VERSION",
    "RenderCache",
    "get_seerapi_db_version",
]
