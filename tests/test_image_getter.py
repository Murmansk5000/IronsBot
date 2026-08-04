# SPDX-License-Identifier: MIT
import asyncio
from pathlib import Path
from typing import Any

import httpx

from ironsbot.integrations.http.clients import HttpClients
from ironsbot.integrations.http.seer_images import HttpSeerImageSource
from ironsbot.integrations.storage.seer_assets import (
    SeerAssetStore,
    SeerAssetStoreLimits,
)

HTTP_NOT_FOUND = 404
HTTP_OK = 200
MAX_ASSET_FETCH_CONCURRENCY = 4


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


async def _fetch_many_images(cache_dir: Path) -> int:
    cache = _ConcurrentDetectingClient()
    clients = HttpClients(cache=cache)
    images = SeerAssetStore(
        HttpSeerImageSource(clients),
        cache_dir,
        SeerAssetStoreLimits(
            memory_max_size_bytes=1024,
            disk_max_size_bytes=1024 * 1024,
            max_network_concurrent=MAX_ASSET_FETCH_CONCURRENCY,
            negative_ttl_seconds=300,
        ),
    )
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


def test_image_fetches_use_bounded_asset_store_concurrency(tmp_path: Path) -> None:
    assert asyncio.run(_fetch_many_images(tmp_path)) == MAX_ASSET_FETCH_CONCURRENCY


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
