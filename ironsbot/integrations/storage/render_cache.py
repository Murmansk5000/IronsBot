# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.seer.render_cache import RenderCacheEntry

from .verified_file_cache import VerifiedFileCache

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.services.seer.render_cache import RenderCache

UNKNOWN_RENDER_CACHE_VERSION = "unknown"


class FileRenderCache:
    def __init__(
        self,
        cache_dir: Path,
        max_size_bytes: int,
        *,
        version_getter: Callable[[], str],
        category_available: Callable[[str], bool] | None = None,
        scope: str = "",
    ) -> None:
        self._cache = VerifiedFileCache(cache_dir, max_size_bytes)
        self._version_getter = version_getter
        self._category_available = category_available
        self._scope = scope

    def _key(self, category: str, content_key: str) -> str | None:
        if self._category_available is not None and not self._category_available(
            category
        ):
            return None
        version = self._version_getter()
        if version == UNKNOWN_RENDER_CACHE_VERSION:
            return None
        raw = "\0".join(
            ("render-entry-v1", category, content_key, version, self._scope)
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def entry(self, category: str, content_key: str) -> RenderCacheEntry:
        key = self._key(category, content_key)

        def get() -> bytes | None:
            if key is None or self._key(category, content_key) != key:
                return None
            return self._cache.get(key)

        def put(data: bytes) -> None:
            if key is not None and self._key(category, content_key) == key:
                self._cache.put(key, data)

        return RenderCacheEntry(get, put)

    def cleanup(self) -> None:
        self._cache.cleanup()

    def bind(
        self, version: str, category_available: Callable[[str], bool]
    ) -> RenderCache:
        """Keep fully bound renders in their captured release after an update."""
        return _SnapshotRenderCache(
            self._cache,
            version,
            category_available,
            self._scope,
        )


@dataclass(frozen=True, slots=True)
class _SnapshotRenderCache:
    cache: VerifiedFileCache
    version: str
    category_available: Callable[[str], bool]
    scope: str

    def entry(self, category: str, content_key: str) -> RenderCacheEntry:
        allowed = (
            self.version != UNKNOWN_RENDER_CACHE_VERSION
            and self.category_available(category)
        )
        key = hashlib.sha256(
            "\0".join(
                (
                    "render-snapshot-v1",
                    category,
                    content_key,
                    self.version,
                    self.scope,
                )
            ).encode("utf-8")
        ).hexdigest()

        def get() -> bytes | None:
            return self.cache.get(key) if allowed else None

        def put(data: bytes) -> None:
            if allowed:
                self.cache.put(key, data)

        return RenderCacheEntry(get, put)
