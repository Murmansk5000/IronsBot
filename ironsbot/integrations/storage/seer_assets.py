# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared verified cache for Seer image assets."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.seer.images import (
    ImageKind,
    ImageSourceError,
    ImageSourceStatusError,
)

from .verified_file_cache import VerifiedFileCache

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from ironsbot.config.models.seer import RenderConfig
    from ironsbot.services.seer.images import SeerImageRequestSource, SeerImageSource


_NEGATIVE_STATUS_CODES = frozenset({404, 410})


@dataclass(frozen=True, slots=True)
class SeerAssetStoreLimits:
    memory_max_size_bytes: int
    disk_max_size_bytes: int
    max_network_concurrent: int
    negative_ttl_seconds: float


class SeerAssetStore:
    """Cache image fetches with bounded memory, verified disk, and singleflight."""

    def __init__(
        self,
        source: SeerImageRequestSource,
        cache_dir: Path,
        limits: SeerAssetStoreLimits,
    ) -> None:
        self._source = source
        self._memory = _MemoryAssetCache(limits.memory_max_size_bytes)
        self._disk = VerifiedFileCache(cache_dir, limits.disk_max_size_bytes)
        self._network = asyncio.Semaphore(limits.max_network_concurrent)
        self._negative_ttl_seconds = limits.negative_ttl_seconds
        self._negative: dict[str, float] = {}
        self._inflight: dict[str, asyncio.Task[bytes]] = {}

    async def fetch(
        self,
        kind: ImageKind,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        return await self._fetch_from(self._source, kind, key, fallback=fallback)

    def bind(self, source: SeerImageRequestSource) -> SeerImageSource:
        """Reuse storage and concurrency limits with an immutable request source."""
        return _BoundAssetSource(self, source)

    async def _fetch_from(
        self,
        source: SeerImageRequestSource,
        kind: ImageKind,
        key: str,
        *,
        fallback: bool,
    ) -> bytes:
        request = source.prepare(kind, key, fallback=fallback)
        cache_key = _cache_key(
            "prepared-image-v1",
            request.identity,
            kind,
            key,
            str(fallback),
        )
        return await self._get_or_fetch(
            cache_key,
            request.fetch,
        )

    async def fetch_url(self, url: str) -> bytes:
        cache_key = _cache_key("url", url)
        return await self._get_or_fetch(cache_key, lambda: self._source.fetch_url(url))

    async def _get_or_fetch(
        self,
        cache_key: str,
        fetch: Callable[[], Awaitable[bytes]],
    ) -> bytes:
        if (asset := self._memory.get(cache_key)) is not None:
            return asset
        if self._is_negative(cache_key):
            raise ImageSourceStatusError(404, "cached missing image")
        return await self._await_shared_fetch(cache_key, fetch)

    async def _await_shared_fetch(
        self,
        cache_key: str,
        fetch: Callable[[], Awaitable[bytes]],
    ) -> bytes:
        task = self._inflight.get(cache_key)
        if task is None:
            task = asyncio.create_task(self._load_or_fetch(cache_key, fetch))
            self._inflight[cache_key] = task
            task.add_done_callback(lambda done: self._finish_fetch(cache_key, done))
        return await asyncio.shield(task)

    def _finish_fetch(self, cache_key: str, task: asyncio.Task[bytes]) -> None:
        if self._inflight.get(cache_key) is task:
            self._inflight.pop(cache_key)
        if not task.cancelled():
            task.exception()

    async def _load_or_fetch(
        self,
        cache_key: str,
        fetch: Callable[[], Awaitable[bytes]],
    ) -> bytes:
        if (asset := await asyncio.to_thread(self._disk.get, cache_key)) is not None:
            self._memory.put(cache_key, asset)
            return asset
        return await self._fetch_and_store(cache_key, fetch)

    async def _fetch_and_store(
        self,
        cache_key: str,
        fetch: Callable[[], Awaitable[bytes]],
    ) -> bytes:
        try:
            async with self._network:
                asset = await fetch()
        except ImageSourceStatusError as error:
            if error.status_code in _NEGATIVE_STATUS_CODES:
                self._negative[cache_key] = (
                    time.monotonic() + self._negative_ttl_seconds
                )
            raise
        except ImageSourceError:
            raise
        if not asset:
            raise ImageSourceError("图片响应为空")
        self._negative.pop(cache_key, None)
        self._memory.put(cache_key, asset)
        await asyncio.to_thread(self._disk.put, cache_key, asset)
        return asset

    def _is_negative(self, cache_key: str) -> bool:
        expires_at = self._negative.get(cache_key)
        if expires_at is None:
            return False
        if expires_at > time.monotonic():
            return True
        self._negative.pop(cache_key, None)
        return False


@dataclass(frozen=True, slots=True)
class _BoundAssetSource:
    store: SeerAssetStore
    source: SeerImageRequestSource

    async def fetch(self, kind: ImageKind, key: str, *, fallback: bool = True) -> bytes:
        return await self.store._fetch_from(self.source, kind, key, fallback=fallback)

    async def fetch_url(self, url: str) -> bytes:
        return await self.store._get_or_fetch(
            _cache_key("url", url), lambda: self.source.fetch_url(url)
        )


class _MemoryAssetCache:
    def __init__(self, max_size_bytes: int) -> None:
        self._max_size_bytes = max_size_bytes
        self._size_bytes = 0
        self._entries: OrderedDict[str, bytes] = OrderedDict()

    def get(self, key: str) -> bytes | None:
        value = self._entries.pop(key, None)
        if value is not None:
            self._entries[key] = value
        return value

    def put(self, key: str, value: bytes) -> None:
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._size_bytes -= len(previous)
        if len(value) > self._max_size_bytes:
            return
        self._entries[key] = value
        self._size_bytes += len(value)
        while self._size_bytes > self._max_size_bytes:
            _key, evicted = self._entries.popitem(last=False)
            self._size_bytes -= len(evicted)


def _cache_key(*parts: str) -> str:
    encoded = "\0".join(parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_seer_asset_store(
    source: SeerImageRequestSource,
    cache_dir: Path,
    render_config: RenderConfig,
) -> SeerAssetStore:
    """Build the shared Seer image asset port from application configuration."""
    return SeerAssetStore(
        source,
        cache_dir,
        SeerAssetStoreLimits(
            memory_max_size_bytes=(
                render_config.asset_memory_max_size_mb * 1024 * 1024
            ),
            disk_max_size_bytes=(render_config.asset_cache_max_size_mb * 1024 * 1024),
            max_network_concurrent=render_config.asset_fetch_max_concurrent,
            negative_ttl_seconds=render_config.asset_negative_ttl_seconds,
        ),
    )
