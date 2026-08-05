# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

UNKNOWN_RENDER_CACHE_VERSION = "unknown"


class FileRenderCache:
    def __init__(
        self,
        cache_dir: Path,
        max_size_bytes: int,
        *,
        db_version_getter: Callable[[], str],
    ) -> None:
        self._cache_dir = cache_dir
        self._max_size_bytes = max_size_bytes
        self._db_version_getter = db_version_getter

    def _path(self, category: str, content_key: str) -> Path | None:
        version = self._db_version_getter()
        if version == UNKNOWN_RENDER_CACHE_VERSION:
            return None
        version_hash = hashlib.sha256(version.encode()).hexdigest()[:12]
        return self._cache_dir / f"{category}_{content_key}_{version_hash}.png"

    def get(self, category: str, content_key: str) -> bytes | None:
        path = self._path(category, content_key)
        return path.read_bytes() if path is not None and path.exists() else None

    def put(self, category: str, content_key: str, data: bytes) -> None:
        path = self._path(category, content_key)
        if path is None:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.cleanup()

    def cleanup(self) -> None:
        if not self._cache_dir.exists():
            return
        files = [path for path in self._cache_dir.iterdir() if path.is_file()]
        total_size = sum(path.stat().st_size for path in files)
        if total_size <= self._max_size_bytes:
            return

        files.sort(key=lambda path: path.stat().st_mtime)
        for path in files:
            if total_size <= self._max_size_bytes:
                break
            total_size -= path.stat().st_size
            path.unlink(missing_ok=True)
