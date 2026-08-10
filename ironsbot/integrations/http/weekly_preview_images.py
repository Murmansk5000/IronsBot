# SPDX-License-Identifier: MIT
"""Disk-backed HTTP source for the mutable weekly preview image."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from httpx import AsyncClient, HTTPStatusError, RequestError

from ironsbot.services.seer.weekly_preview import WEEKLY_PREVIEW_MIRROR_URL
from ironsbot.services.seer.weekly_preview_images import (
    WeeklyPreviewImage,
    WeeklyPreviewImageError,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.core.tasks import TaskSpawner

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_WEEKLY_PREVIEW_BYTES = 10 * 1024 * 1024
WEEKLY_PREVIEW_FRESH_TTL = timedelta(minutes=5)
WEEKLY_PREVIEW_STALE_TTL = timedelta(hours=24)
HTTP_NOT_MODIFIED = 304


class _NaiveClockError(ValueError):
    def __init__(self) -> None:
        super().__init__("weekly preview cache clock must be timezone-aware")


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    data: bytes
    cached_at: datetime
    source_url: str
    etag: str = ""
    last_modified: str = ""


class CachedWeeklyPreviewImageSource:
    def __init__(
        self,
        client: AsyncClient,
        cache_dir: Path,
        *,
        spawn: TaskSpawner,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._image_path = cache_dir / "weekly_preview.png"
        self._metadata_path = cache_dir / "weekly_preview.json"
        self._spawn = spawn
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._inflight_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task[WeeklyPreviewImage]] = {}

    async def fetch(self, primary_url: str) -> WeeklyPreviewImage:
        now = self._now()
        cached = self._read_cache()
        if cached is not None and now - cached.cached_at <= WEEKLY_PREVIEW_FRESH_TTL:
            return _to_result(cached)

        async with self._inflight_lock:
            task = self._inflight.get(primary_url)
            if task is None:
                task = self._spawn(
                    self._refresh(primary_url),
                    name="weekly-preview-refresh",
                )
                self._inflight[primary_url] = task
        try:
            return await asyncio.shield(task)
        finally:
            async with self._inflight_lock:
                if self._inflight.get(primary_url) is task and task.done():
                    self._inflight.pop(primary_url, None)

    async def _refresh(self, primary_url: str) -> WeeklyPreviewImage:
        cached = self._read_cache()
        now = self._now()
        failures: list[str] = []
        sources = tuple(dict.fromkeys((primary_url, WEEKLY_PREVIEW_MIRROR_URL)))
        for index, source_url in enumerate(sources):
            request_url = source_url
            headers: dict[str, str] = {}
            if index == 0 and cached is not None and cached.source_url == source_url:
                if cached.etag:
                    headers["If-None-Match"] = cached.etag
                if cached.last_modified:
                    headers["If-Modified-Since"] = cached.last_modified
            elif source_url == WEEKLY_PREVIEW_MIRROR_URL:
                request_url = _with_cache_version(source_url, now)

            try:
                response = await self._client.get(request_url, headers=headers)
                if response.status_code == HTTP_NOT_MODIFIED:
                    refreshed = _refresh_not_modified_cache(
                        cached,
                        now,
                        source_url,
                    )
                    self._write_cache(refreshed)
                    return _to_result(refreshed)
                response.raise_for_status()
                _validate_png(response.content)
                refreshed = _CacheEntry(
                    data=response.content,
                    cached_at=now,
                    source_url=source_url,
                    etag=response.headers.get("etag", ""),
                    last_modified=response.headers.get("last-modified", ""),
                )
                self._write_cache(refreshed)
                return _to_result(refreshed)
            except (HTTPStatusError, RequestError, WeeklyPreviewImageError) as error:
                failures.append(_format_source_failure(source_url, error))

        failure_message = "; ".join(failures)
        if cached is not None and now - cached.cached_at <= WEEKLY_PREVIEW_STALE_TTL:
            logger.warning(
                "weekly preview refresh failed; using cached image: %s",
                failure_message,
            )
            return WeeklyPreviewImage(
                data=cached.data,
                cached_at=cached.cached_at,
                source_url=cached.source_url,
                stale=True,
                refresh_error=failure_message,
            )
        raise WeeklyPreviewImageError.from_detail(
            failure_message or "all preview sources failed"
        )

    def _read_cache(self) -> _CacheEntry | None:
        try:
            data = self._image_path.read_bytes()
            metadata = json.loads(self._metadata_path.read_text(encoding="utf-8"))
            _validate_png(data)
            if hashlib.sha256(data).hexdigest() != str(metadata["sha256"]):
                return None
            cached_at = datetime.fromisoformat(str(metadata["cached_at"]))
            if cached_at.tzinfo is None or cached_at.utcoffset() is None:
                return None
            return _CacheEntry(
                data=data,
                cached_at=cached_at.astimezone(timezone.utc),
                source_url=str(metadata["source_url"]),
                etag=str(metadata.get("etag", "")),
                last_modified=str(metadata.get("last_modified", "")),
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _write_cache(self, entry: _CacheEntry) -> None:
        image_tmp = self._image_path.with_suffix(".png.tmp")
        metadata_tmp = self._metadata_path.with_suffix(".json.tmp")
        metadata: dict[str, Any] = {
            "cached_at": entry.cached_at.astimezone(timezone.utc).isoformat(),
            "source_url": entry.source_url,
            "etag": entry.etag,
            "last_modified": entry.last_modified,
            "sha256": hashlib.sha256(entry.data).hexdigest(),
        }
        try:
            self._image_path.parent.mkdir(parents=True, exist_ok=True)
            image_tmp.write_bytes(entry.data)
            metadata_tmp.write_text(
                json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )
            image_tmp.replace(self._image_path)
            metadata_tmp.replace(self._metadata_path)
        except OSError:
            logger.warning("failed to update weekly preview image cache", exc_info=True)
        finally:
            with suppress(OSError):
                image_tmp.unlink(missing_ok=True)
            with suppress(OSError):
                metadata_tmp.unlink(missing_ok=True)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise _NaiveClockError
        return now.astimezone(timezone.utc)


def _validate_png(data: bytes) -> None:
    if not data.startswith(PNG_SIGNATURE):
        raise WeeklyPreviewImageError.invalid_png()
    if len(data) > MAX_WEEKLY_PREVIEW_BYTES:
        raise WeeklyPreviewImageError.image_too_large(MAX_WEEKLY_PREVIEW_BYTES)


def _refresh_not_modified_cache(
    cached: _CacheEntry | None,
    now: datetime,
    source_url: str,
) -> _CacheEntry:
    if cached is None:
        raise WeeklyPreviewImageError.missing_cache_for_not_modified(source_url)
    return replace(cached, cached_at=now, source_url=source_url)


def _with_cache_version(url: str, now: datetime) -> str:
    separator = "&" if "?" in url else "?"
    minute_bucket = now.minute - now.minute % 5
    version = now.replace(minute=minute_bucket, second=0, microsecond=0)
    return f"{url}{separator}v={version:%Y%m%d%H%M}"


def _format_source_failure(source_url: str, error: Exception) -> str:
    if isinstance(error, HTTPStatusError):
        detail = f"{error.response.status_code} {error.response.reason_phrase}"
    else:
        detail = str(error).strip() or type(error).__name__
    return f"{source_url}: {detail}"


def _to_result(entry: _CacheEntry) -> WeeklyPreviewImage:
    return WeeklyPreviewImage(
        data=entry.data,
        cached_at=entry.cached_at,
        source_url=entry.source_url,
    )
