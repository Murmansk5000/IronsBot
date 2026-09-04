# SPDX-License-Identifier: MIT
import asyncio
from io import BytesIO
from typing import Any

import httpx
import pytest
from PIL import Image

from ironsbot.integrations.http.clients import HttpClients
from ironsbot.integrations.http.seer_images import HttpSeerImageSource
from ironsbot.services.seer.images import ImageSourceError

HTTP_NOT_FOUND = 404
HTTP_OK = 200
MINTMARK_SOURCE_COUNT = 2


class _ConcurrentDetectingClient(httpx.AsyncClient):
    def __init__(self) -> None:
        super().__init__()
        self.in_flight = 0
        self.max_in_flight = 0

    async def get(self, url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        _ = (args, kwargs)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        return httpx.Response(
            200,
            content=b"image",
            request=httpx.Request("GET", url),
        )


class _ItemFallbackClient(httpx.AsyncClient):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    async def get(self, url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        _ = (args, kwargs)
        self.urls.append(url)
        status_code = HTTP_NOT_FOUND if "/doodle/" in url else HTTP_OK
        return httpx.Response(
            status_code,
            content=b"item-image" if status_code == HTTP_OK else b"",
            request=httpx.Request("GET", url),
        )


class _PreviewFallbackClient(httpx.AsyncClient):
    def __init__(self, *, fail_all: bool = False) -> None:
        super().__init__()
        self.fail_all = fail_all
        self.urls: list[str] = []

    async def get(self, url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        _ = (args, kwargs)
        self.urls.append(url)
        request = httpx.Request("GET", url)
        if self.fail_all or "raw.githubusercontent.com" in url:
            raise httpx.ConnectError("", request=request)
        return httpx.Response(HTTP_OK, content=b"preview", request=request)


async def _fetch_many_images() -> int:
    cache = _ConcurrentDetectingClient()
    clients = HttpClients(cache=cache)
    images = HttpSeerImageSource(clients)
    try:
        await asyncio.gather(
            *(
                images.fetch("pet_body", str(i), fallback=False)
                for i in range(8)
            )
        )
        return cache.max_in_flight
    finally:
        await clients.close()


async def _fetch_item_from_fallback_source() -> tuple[bytes, list[str]]:
    cache = _ItemFallbackClient()
    clients = HttpClients(cache=cache)
    images = HttpSeerImageSource(clients)
    try:
        return await images.fetch("item", "1726710", fallback=False), cache.urls
    finally:
        await clients.close()


async def _fetch_sign_buff() -> tuple[bytes, list[str]]:
    cache = _ItemFallbackClient()
    clients = HttpClients(cache=cache)
    images = HttpSeerImageSource(clients)
    try:
        return await images.fetch("sign_buff", "33", fallback=False), cache.urls
    finally:
        await clients.close()


async def _fetch_preview_from_fallback() -> tuple[bytes, list[str]]:
    origin = _PreviewFallbackClient()
    clients = HttpClients(origin=origin)
    images = HttpSeerImageSource(clients)
    try:
        return await images.fetch("preview", "", fallback=False), origin.urls
    finally:
        await clients.close()


async def _fetch_preview_failure() -> None:
    origin = _PreviewFallbackClient(fail_all=True)
    clients = HttpClients(origin=origin)
    images = HttpSeerImageSource(clients)
    try:
        await images.fetch("preview", "", fallback=False)
    finally:
        await clients.close()


async def _fetch_mintmark_with_all_sources_unavailable() -> tuple[bytes, list[str]]:
    cache = _PreviewFallbackClient(fail_all=True)
    clients = HttpClients(cache=cache)
    images = HttpSeerImageSource(clients)
    try:
        return await images.fetch("mintmark", "20447"), cache.urls
    finally:
        await clients.close()


def test_image_fetches_are_serialized_for_shared_cache_client() -> None:
    assert asyncio.run(_fetch_many_images()) == 1


def test_item_image_tries_known_asset_categories() -> None:
    data, urls = asyncio.run(_fetch_item_from_fallback_source())

    assert data == b"item-image"
    assert "/item/doodle/icon/1726710.png" in urls[0]
    assert "/item/petitem/icon/1726710.png" in urls[1]


def test_sign_buff_image_uses_official_battle_effect_assets() -> None:
    data, urls = asyncio.run(_fetch_sign_buff())

    assert data == b"item-image"
    assert urls == [
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
        "newseer/assets/art/ui/assets/battleeffect/signbuff/33.png"
    ]


def test_preview_image_uses_independent_cdn_fallback() -> None:
    data, urls = asyncio.run(_fetch_preview_from_fallback())

    assert data == b"preview"
    assert "raw.githubusercontent.com" in urls[0]
    assert "cdn.jsdelivr.net" in urls[1]


def test_empty_image_request_error_keeps_actionable_details() -> None:
    with pytest.raises(ImageSourceError) as captured:
        asyncio.run(_fetch_preview_failure())

    assert "ConnectError" in str(captured.value)
    assert "cdn.jsdelivr.net" in str(captured.value)


def test_mintmark_uses_local_png_when_all_remote_assets_are_unavailable() -> None:
    data, urls = asyncio.run(_fetch_mintmark_with_all_sources_unavailable())

    assert len(urls) == MINTMARK_SOURCE_COUNT
    assert all("dummyimage.com" not in url for url in urls)
    with Image.open(BytesIO(data)) as image:
        assert image.format == "PNG"
        assert image.size == (96, 96)
