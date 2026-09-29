# SPDX-License-Identifier: MIT
"""Disk-backed HTTP source for the mutable weekly preview image."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from httpx import AsyncClient, HTTPStatusError, RequestError, Response

from ironsbot.integrations.seer_data.weekly_preview_repository import (
    DEFAULT_WEEKLY_PREVIEW_IMAGE_URL,
    weekly_preview_api_url,
    weekly_preview_mirror_url,
)
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
GIT_BLOB_SHA_LENGTH = 40
INVALID_API_METADATA = "GitHub API returned invalid image metadata"
INVALID_API_CONTENT = "GitHub API returned invalid image content"


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
        self._cache_dir = cache_dir
        self._spawn = spawn
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._inflight_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task[WeeklyPreviewImage]] = {}

    async def fetch(self, primary_url: str) -> WeeklyPreviewImage:
        now = self._now()
        image_path, metadata_path = self._cache_paths(primary_url)
        cached = self._read_cache(image_path, metadata_path)
        if cached is not None and now - cached.cached_at <= WEEKLY_PREVIEW_FRESH_TTL:
            return _to_result(cached)

        async with self._inflight_lock:
            task = self._inflight.get(primary_url)
            if task is None:
                task = self._spawn(
                    self._refresh(primary_url, image_path, metadata_path),
                    name=f"weekly-preview-refresh-{_url_cache_key(primary_url)}",
                )
                self._inflight[primary_url] = task
        try:
            return await asyncio.shield(task)
        finally:
            async with self._inflight_lock:
                if self._inflight.get(primary_url) is task and task.done():
                    self._inflight.pop(primary_url, None)

    async def _refresh(
        self,
        primary_url: str,
        image_path: Path,
        metadata_path: Path,
    ) -> WeeklyPreviewImage:
        cached = self._read_cache(image_path, metadata_path)
        now = self._now()
        failures: list[str] = []
        mirror_url = weekly_preview_mirror_url(primary_url)
        sources = tuple(dict.fromkeys(url for url in (primary_url, mirror_url) if url))
        for index, source_url in enumerate(sources):
            request_url = source_url
            headers: dict[str, str] = {}
            if index == 0 and cached is not None and cached.source_url == source_url:
                if cached.etag:
                    headers["If-None-Match"] = cached.etag
                if cached.last_modified:
                    headers["If-Modified-Since"] = cached.last_modified
            elif source_url == mirror_url:
                request_url = _with_cache_version(source_url, now)

            try:
                response = await self._client.get(request_url, headers=headers)
                if response.status_code == HTTP_NOT_MODIFIED:
                    refreshed = _refresh_not_modified_cache(
                        cached,
                        now,
                        source_url,
                    )
                    self._write_cache(refreshed, image_path, metadata_path)
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
                self._write_cache(refreshed, image_path, metadata_path)
                return _to_result(refreshed)
            except (HTTPStatusError, RequestError, WeeklyPreviewImageError) as error:
                failures.append(_format_source_failure(source_url, error))

        api_result = await self._try_github_api(primary_url, now, failures)
        if api_result is not None:
            return api_result

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

    async def _try_github_api(
        self, primary_url: str, now: datetime, failures: list[str]
    ) -> WeeklyPreviewImage | None:
        api_url = weekly_preview_api_url(primary_url)
        if not api_url:
            return None
        try:
            data = await self._fetch_github_api_image(api_url)
            _validate_png(data)
            refreshed = _CacheEntry(data=data, cached_at=now, source_url=api_url)
            self._write_cache(refreshed, *self._cache_paths(primary_url))
            return _to_result(refreshed)
        except (HTTPStatusError, RequestError, WeeklyPreviewImageError) as error:
            failures.append(_format_source_failure(api_url, error))
            return None

    async def _fetch_github_api_image(self, api_url: str) -> bytes:
        metadata_response = await self._client.get(api_url)
        metadata_response.raise_for_status()
        metadata = _github_api_json(metadata_response, INVALID_API_METADATA)
        sha = metadata.get("sha") if isinstance(metadata, dict) else None
        if (
            not isinstance(sha, str)
            or len(sha) != GIT_BLOB_SHA_LENGTH
            or not all(character in "0123456789abcdef" for character in sha)
        ):
            raise WeeklyPreviewImageError.from_detail(INVALID_API_METADATA)

        blob_url = (
            "https://api.github.com/repos/Murmansk-Seer/"
            f"seer-unity-preview-img-dumper/git/blobs/{sha}"
        )
        blob_response = await self._client.get(blob_url)
        blob_response.raise_for_status()
        blob = _github_api_json(blob_response, INVALID_API_CONTENT)
        if (
            not isinstance(blob, dict)
            or blob.get("sha") != sha
            or blob.get("encoding") != "base64"
        ):
            raise WeeklyPreviewImageError.from_detail(INVALID_API_CONTENT)
        content = blob.get("content")
        if not isinstance(content, str) or len(content) > (
            (MAX_WEEKLY_PREVIEW_BYTES + 2) // 3 * 4 + 100_000
        ):
            raise WeeklyPreviewImageError.from_detail(INVALID_API_CONTENT)
        try:
            return base64.b64decode("".join(content.split()), validate=True)
        except (ValueError, binascii.Error) as error:
            raise WeeklyPreviewImageError.from_detail(INVALID_API_CONTENT) from error

    def _read_cache(
        self,
        image_path: Path,
        metadata_path: Path,
    ) -> _CacheEntry | None:
        try:
            data = image_path.read_bytes()
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
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

    def _write_cache(
        self,
        entry: _CacheEntry,
        image_path: Path,
        metadata_path: Path,
    ) -> None:
        image_tmp = image_path.with_suffix(".png.tmp")
        metadata_tmp = metadata_path.with_suffix(".json.tmp")
        metadata: dict[str, Any] = {
            "cached_at": entry.cached_at.astimezone(timezone.utc).isoformat(),
            "source_url": entry.source_url,
            "etag": entry.etag,
            "last_modified": entry.last_modified,
            "sha256": hashlib.sha256(entry.data).hexdigest(),
        }
        try:
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_tmp.write_bytes(entry.data)
            metadata_tmp.write_text(
                json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )
            image_tmp.replace(image_path)
            metadata_tmp.replace(metadata_path)
        except OSError:
            logger.warning("failed to update weekly preview image cache", exc_info=True)
        finally:
            with suppress(OSError):
                image_tmp.unlink(missing_ok=True)
            with suppress(OSError):
                metadata_tmp.unlink(missing_ok=True)

    def _cache_paths(self, primary_url: str) -> tuple[Path, Path]:
        suffix = (
            ""
            if primary_url == DEFAULT_WEEKLY_PREVIEW_IMAGE_URL
            else (f"_{_url_cache_key(primary_url)}")
        )
        return (
            self._cache_dir / f"weekly_preview{suffix}.png",
            self._cache_dir / f"weekly_preview{suffix}.json",
        )

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


def _github_api_json(response: Response, error_detail: str) -> Any:
    try:
        return response.json()
    except ValueError as error:
        raise WeeklyPreviewImageError.from_detail(error_detail) from error


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


def _url_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


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
