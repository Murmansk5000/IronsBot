# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared verified cache for Seer image assets."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.seer.images import (
    ImageKind,
    ImageSourceError,
    ImageSourceStatusError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from ironsbot.config.models.seer import RenderConfig
    from ironsbot.services.seer.images import SeerImageSource


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
        source: SeerImageSource,
        cache_dir: Path,
        limits: SeerAssetStoreLimits,
    ) -> None:
        self._source = source
        self._memory = _MemoryAssetCache(limits.memory_max_size_bytes)
        self._disk = _DiskAssetCache(cache_dir, limits.disk_max_size_bytes)
        self._network = asyncio.Semaphore(limits.max_network_concurrent)
        self._negative_ttl_seconds = limits.negative_ttl_seconds
        self._negative: dict[str, float] = {}
        self._inflight: dict[str, asyncio.Future[bytes]] = {}
        self._inflight_lock = asyncio.Lock()

    async def fetch(
        self,
        kind: ImageKind,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        cache_key = _cache_key("image", kind, key, str(fallback))
        return await self._get_or_fetch(
            cache_key,
            lambda: self._source.fetch(kind, key, fallback=fallback),
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
        if (asset := await asyncio.to_thread(self._disk.get, cache_key)) is not None:
            self._memory.put(cache_key, asset)
            return asset
        return await self._await_shared_fetch(cache_key, fetch)

    async def _await_shared_fetch(
        self,
        cache_key: str,
        fetch: Callable[[], Awaitable[bytes]],
    ) -> bytes:
        async with self._inflight_lock:
            future = self._inflight.get(cache_key)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                future.add_done_callback(_consume_future_exception)
                self._inflight[cache_key] = future
                is_owner = True
            else:
                is_owner = False
        if not is_owner:
            return await asyncio.shield(future)

        try:
            asset = await self._fetch_and_store(cache_key, fetch)
        except asyncio.CancelledError:
            future.cancel()
            raise
        except BaseException as error:
            future.set_exception(error)
            raise
        else:
            future.set_result(asset)
            return asset
        finally:
            async with self._inflight_lock:
                if self._inflight.get(cache_key) is future:
                    self._inflight.pop(cache_key, None)

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


class _DiskAssetCache:
    def __init__(self, directory: Path, max_size_bytes: int) -> None:
        self._directory = directory
        self._max_size_bytes = max_size_bytes

    def get(self, cache_key: str) -> bytes | None:
        index_path = self._index_path(cache_key)
        try:
            metadata = json.loads(index_path.read_text(encoding="utf-8"))
            digest = str(metadata["sha256"])
            asset_path = self._asset_path(cache_key, digest)
            asset = asset_path.read_bytes()
        except (FileNotFoundError, OSError, TypeError, ValueError, KeyError):
            return None
        if hashlib.sha256(asset).hexdigest() != digest:
            self._remove_entry(index_path, asset_path)
            return None
        os.utime(asset_path, None)
        return asset

    def put(self, cache_key: str, asset: bytes) -> None:
        digest = hashlib.sha256(asset).hexdigest()
        asset_path = self._asset_path(cache_key, digest)
        index_path = self._index_path(cache_key)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._atomic_write_bytes(asset_path, asset)
        self._atomic_write_text(
            index_path,
            json.dumps({"sha256": digest}, separators=(",", ":")),
        )
        self._cleanup()

    def _cleanup(self) -> None:
        if not self._directory.exists():
            return
        indexed_assets = self._indexed_assets()
        assets = sorted(
            self._directory.glob("*.bin"),
            key=lambda path: path.stat().st_atime,
        )
        total_size = sum(path.stat().st_size for path in assets)
        for asset_path in assets:
            if total_size <= self._max_size_bytes:
                break
            size = asset_path.stat().st_size
            total_size -= size
            asset_path.unlink(missing_ok=True)
            if (index_path := indexed_assets.get(asset_path.name)) is not None:
                index_path.unlink(missing_ok=True)

    def _indexed_assets(self) -> dict[str, Path]:
        indexed: dict[str, Path] = {}
        for index_path in self._directory.glob("*.json"):
            try:
                metadata = json.loads(index_path.read_text(encoding="utf-8"))
                digest = str(metadata["sha256"])
            except (OSError, TypeError, ValueError, KeyError):
                index_path.unlink(missing_ok=True)
                continue
            asset_path = self._asset_path(index_path.stem, digest)
            if asset_path.exists():
                indexed[asset_path.name] = index_path
            else:
                index_path.unlink(missing_ok=True)
        return indexed

    def _index_path(self, cache_key: str) -> Path:
        return self._directory / f"{cache_key}.json"

    def _asset_path(self, cache_key: str, digest: str) -> Path:
        return self._directory / f"{cache_key}-{digest}.bin"

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes) -> None:
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    @staticmethod
    def _atomic_write_text(path: Path, value: str) -> None:
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(value, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _remove_entry(index_path: Path, asset_path: Path) -> None:
        index_path.unlink(missing_ok=True)
        asset_path.unlink(missing_ok=True)


def _cache_key(*parts: str) -> str:
    encoded = "\0".join(parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _consume_future_exception(future: asyncio.Future[bytes]) -> None:
    if future.cancelled():
        return
    _ = future.exception()


def build_seer_asset_store(
    source: SeerImageSource,
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
            disk_max_size_bytes=(
                render_config.asset_cache_max_size_mb * 1024 * 1024
            ),
            max_network_concurrent=render_config.asset_fetch_max_concurrent,
            negative_ttl_seconds=render_config.asset_negative_ttl_seconds,
        ),
    )
