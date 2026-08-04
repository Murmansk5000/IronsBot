# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from .verified_file_cache import VerifiedFileCache

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
        version_getter: Callable[[], str],
    ) -> None:
        self._cache = VerifiedFileCache(cache_dir, max_size_bytes)
        self._version_getter = version_getter

    def _key(self, category: str, content_key: str) -> str | None:
        version = self._version_getter()
        if version == UNKNOWN_RENDER_CACHE_VERSION:
            return None
        raw = "\0".join((category, content_key, version)).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def get(self, category: str, content_key: str) -> bytes | None:
        key = self._key(category, content_key)
        return self._cache.get(key) if key is not None else None

    def put(self, category: str, content_key: str, data: bytes) -> None:
        key = self._key(category, content_key)
        if key is None:
            return
        self._cache.put(key, data)

    def cleanup(self) -> None:
        self._cache.cleanup()
