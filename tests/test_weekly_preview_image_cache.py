# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from shutil import rmtree
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from ironsbot.integrations.http.weekly_preview_images import (
    MAX_WEEKLY_PREVIEW_BYTES,
    CachedWeeklyPreviewImageSource,
)
from ironsbot.services.seer.weekly_preview import WEEKLY_PREVIEW_MIRROR_URL
from ironsbot.services.seer.weekly_preview_images import WeeklyPreviewImageError

if TYPE_CHECKING:
    from pathlib import Path

PRIMARY_URL = "https://raw.example.test/preview.png"
PNG = b"\x89PNG\r\n\x1a\npreview"


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def _build_source(
    tmp_path: Path,
    handler: Any,
    clock: _Clock,
) -> tuple[CachedWeeklyPreviewImageSource, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        CachedWeeklyPreviewImageSource(
            client,
            tmp_path / "cache" / "assets",
            spawn=lambda coroutine, *, name: asyncio.create_task(
                coroutine,
                name=name,
            ),
            clock=clock,
        ),
        client,
    )


@pytest.mark.asyncio
async def test_fresh_cache_skips_network(tmp_path: Path) -> None:
    calls = 0
    clock = _Clock()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=PNG, request=request)

    source, client = _build_source(tmp_path, handler, clock)
    try:
        first = await source.fetch(PRIMARY_URL)
        clock.advance(timedelta(minutes=4, seconds=59))
        second = await source.fetch(PRIMARY_URL)
    finally:
        await client.aclose()

    assert first.data == second.data == PNG
    assert calls == 1


@pytest.mark.asyncio
async def test_stale_cache_uses_conditional_request(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    clock = _Clock()

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                content=PNG,
                headers={
                    "etag": '"preview-v1"',
                    "last-modified": "Sun, 09 Aug 2026 03:00:00 GMT",
                },
                request=request,
            )
        return httpx.Response(304, request=request)

    source, client = _build_source(tmp_path, handler, clock)
    try:
        await source.fetch(PRIMARY_URL)
        clock.advance(timedelta(minutes=6))
        refreshed = await source.fetch(PRIMARY_URL)
    finally:
        await client.aclose()

    assert refreshed.data == PNG
    assert refreshed.cached_at == clock.now
    assert requests[1].headers["if-none-match"] == '"preview-v1"'
    assert requests[1].headers["if-modified-since"] == (
        "Sun, 09 Aug 2026 03:00:00 GMT"
    )


@pytest.mark.asyncio
async def test_primary_failure_uses_versioned_cdn_mirror(tmp_path: Path) -> None:
    urls: list[str] = []
    clock = _Clock()

    async def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if request.url.host == "raw.example.test":
            raise httpx.ConnectError("", request=request)
        return httpx.Response(200, content=PNG, request=request)

    source, client = _build_source(tmp_path, handler, clock)
    try:
        result = await source.fetch(PRIMARY_URL)
    finally:
        await client.aclose()

    assert result.data == PNG
    assert result.source_url == WEEKLY_PREVIEW_MIRROR_URL
    assert urls[1].startswith(WEEKLY_PREVIEW_MIRROR_URL)
    assert urls[1].endswith("?v=202608100300")


@pytest.mark.asyncio
async def test_remote_failure_uses_cache_for_at_most_24_hours(
    tmp_path: Path,
) -> None:
    failing = False
    clock = _Clock()

    async def handler(request: httpx.Request) -> httpx.Response:
        if failing:
            raise httpx.ConnectError("", request=request)
        return httpx.Response(200, content=PNG, request=request)

    source, client = _build_source(tmp_path, handler, clock)
    try:
        await source.fetch(PRIMARY_URL)
        failing = True
        clock.advance(timedelta(hours=23))
        stale = await source.fetch(PRIMARY_URL)
        clock.advance(timedelta(hours=1, seconds=1))
        with pytest.raises(WeeklyPreviewImageError) as captured:
            await source.fetch(PRIMARY_URL)
    finally:
        await client.aclose()

    assert stale.stale is True
    assert stale.cached_at == datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)
    assert "ConnectError" in stale.refresh_error
    assert PRIMARY_URL in str(captured.value)
    assert WEEKLY_PREVIEW_MIRROR_URL in str(captured.value)


@pytest.mark.asyncio
async def test_invalid_remote_images_do_not_replace_valid_cache(
    tmp_path: Path,
) -> None:
    phase = "valid"
    clock = _Clock()

    async def handler(request: httpx.Request) -> httpx.Response:
        if phase == "valid":
            return httpx.Response(200, content=PNG, request=request)
        if request.url.host == "raw.example.test":
            return httpx.Response(200, content=b"not-png", request=request)
        oversized = b"\x89PNG\r\n\x1a\n" + b"x" * MAX_WEEKLY_PREVIEW_BYTES
        return httpx.Response(200, content=oversized, request=request)

    source, client = _build_source(tmp_path, handler, clock)
    image_path = tmp_path / "cache" / "assets" / "weekly_preview.png"
    try:
        await source.fetch(PRIMARY_URL)
        phase = "invalid"
        clock.advance(timedelta(minutes=6))
        result = await source.fetch(PRIMARY_URL)
    finally:
        await client.aclose()

    assert result.stale is True
    assert result.data == PNG
    assert image_path.read_bytes() == PNG


@pytest.mark.asyncio
async def test_concurrent_queries_share_one_refresh(tmp_path: Path) -> None:
    calls = 0
    clock = _Clock()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return httpx.Response(200, content=PNG, request=request)

    source, client = _build_source(tmp_path, handler, clock)
    try:
        results = await asyncio.gather(*(source.fetch(PRIMARY_URL) for _ in range(8)))
    finally:
        await client.aclose()

    assert calls == 1
    assert all(result.data == PNG for result in results)


@pytest.mark.asyncio
async def test_deleted_cache_directory_is_recreated(tmp_path: Path) -> None:
    content = PNG
    clock = _Clock()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    source, client = _build_source(tmp_path, handler, clock)
    cache_root = tmp_path / "cache"
    try:
        await source.fetch(PRIMARY_URL)
        rmtree(cache_root)
        content = PNG + b"-new"
        clock.advance(timedelta(minutes=6))
        result = await source.fetch(PRIMARY_URL)
    finally:
        await client.aclose()

    assert result.data == PNG + b"-new"
    assert (cache_root / "assets" / "weekly_preview.png").exists()
