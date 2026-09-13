# SPDX-License-Identifier: MIT
import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.integrations.http.clients import HttpClients
from ironsbot.integrations.http.seer_images import HttpSeerImageSource
from ironsbot.integrations.seer_data.pet_image_assets import load_pet_image_assets
from ironsbot.integrations.storage.seer_assets import (
    SeerAssetStore,
    SeerAssetStoreLimits,
)
from ironsbot.services.seer.images import (
    ImageSourceError,
    PublishedAssetRepository,
    PublishedRenderAssetSnapshot,
)

HTTP_NOT_FOUND = 404
HTTP_OK = 200
MAX_ASSET_FETCH_CONCURRENCY = 4
PINNED_ASSET_SOURCE_COUNT = 2


def _asset_snapshot() -> PublishedRenderAssetSnapshot:
    return PublishedRenderAssetSnapshot(
        repositories={
            "default": PublishedAssetRepository(
                "Murmansk-Seer/seer-unity-assets", "a" * 40
            )
        },
        manifest_revision="assets-v2",
        scopes=frozenset({"pet_info"}),
    )


class _ConcurrentDetectingClient(httpx.AsyncClient):
    def __init__(self) -> None:
        super().__init__()
        self.in_flight = 0
        self.max_in_flight = 0
        self.max_started = asyncio.Event()
        self.release = asyncio.Event()

    async def get(self, url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        _ = (args, kwargs)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        if self.in_flight >= MAX_ASSET_FETCH_CONCURRENCY:
            self.max_started.set()
        await self.release.wait()
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
        HttpSeerImageSource(clients, asset_snapshot_getter=_asset_snapshot),
        cache_dir,
        SeerAssetStoreLimits(
            memory_max_size_bytes=1024,
            disk_max_size_bytes=1024 * 1024,
            max_network_concurrent=MAX_ASSET_FETCH_CONCURRENCY,
            negative_ttl_seconds=300,
        ),
        spawn=TaskOwner().create,
    )
    try:
        requests = asyncio.gather(
            *(images.fetch("pet_body", str(i), fallback=False) for i in range(8))
        )
        await asyncio.wait_for(cache.max_started.wait(), timeout=1)
        cache.release.set()
        await requests
        return cache.max_in_flight
    finally:
        await clients.close()


async def _fetch_item_from_fallback_source() -> tuple[bytes, list[str]]:
    cache = _ItemFallbackClient()
    clients = HttpClients(cache=cache)
    images = HttpSeerImageSource(clients, asset_snapshot_getter=_asset_snapshot)
    try:
        return await images.fetch("item", "1726710", fallback=False), cache.urls
    finally:
        await clients.close()


async def _fetch_sign_buff() -> tuple[bytes, list[str]]:
    cache = _ItemFallbackClient()
    clients = HttpClients(cache=cache)
    images = HttpSeerImageSource(clients, asset_snapshot_getter=_asset_snapshot)
    try:
        return await images.fetch("sign_buff", "33", fallback=False), cache.urls
    finally:
        await clients.close()


async def _fetch_without_asset_snapshot() -> list[str]:
    cache = _ItemFallbackClient()
    clients = HttpClients(cache=cache)
    images = HttpSeerImageSource(clients, asset_snapshot_getter=lambda: None)
    try:
        with pytest.raises(ImageSourceError):
            await images.fetch("pet_head", "1", fallback=False)
        return cache.urls
    finally:
        await clients.close()


def test_image_fetches_use_bounded_asset_store_concurrency(tmp_path: Path) -> None:
    assert asyncio.run(_fetch_many_images(tmp_path)) == MAX_ASSET_FETCH_CONCURRENCY


def test_item_image_tries_known_asset_categories() -> None:
    data, urls = asyncio.run(_fetch_item_from_fallback_source())

    assert data == b"item-image"
    assert "/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/" in urls[0]
    assert "/item/doodle/icon/1726710.png" in urls[0]
    assert "@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/" in urls[1]
    assert "/item/doodle/icon/1726710.png" in urls[1]
    assert "/item/petitem/icon/1726710.png" in urls[2]


def test_sign_buff_image_uses_official_battle_effect_assets() -> None:
    data, urls = asyncio.run(_fetch_sign_buff())

    assert data == b"item-image"
    assert urls == [
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/"
        "newseer/assets/art/ui/assets/battleeffect/signbuff/33.png"
    ]


@pytest.mark.asyncio
async def test_pinned_asset_retries_same_revision_through_cdn() -> None:
    urls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        status = (
            HTTP_NOT_FOUND
            if request.url.host == "raw.githubusercontent.com"
            else HTTP_OK
        )
        return httpx.Response(status, content=b"item-image")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=_asset_snapshot,
        )
        assert await source.fetch("sign_buff", "33", fallback=False) == b"item-image"

    assert len(urls) == PINNED_ASSET_SOURCE_COUNT
    assert "/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/" in urls[0]
    assert "@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/" in urls[1]
    assert urls[0].endswith("/signbuff/33.png")
    assert urls[1].endswith("/signbuff/33.png")


@pytest.mark.asyncio
async def test_mount_uses_its_generated_repository_revision() -> None:
    urls: list[str] = []
    snapshot = replace(
        _asset_snapshot(),
        repositories={
            **_asset_snapshot().repositories,
            "mount": PublishedAssetRepository("example/seerapi", "b" * 40),
        },
    )

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        status = HTTP_NOT_FOUND if "seer-unity-assets" in request.url.path else HTTP_OK
        return httpx.Response(status, content=b"mount")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=lambda: snapshot,
        )
        assert await source.fetch("mount", "1301170", fallback=False) == b"mount"

    assert urls == [
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/"
        f"{'a' * 40}/newseer/assets/art/ui/assets/item/cloth/prev/1301170.png",
        "https://cdn.jsdelivr.net/gh/Murmansk-Seer/seer-unity-assets@"
        f"{'a' * 40}/newseer/assets/art/ui/assets/item/cloth/prev/1301170.png",
        "https://raw.githubusercontent.com/example/seerapi/"
        f"{'b' * 40}/mount/1301170.png",
    ]


@pytest.mark.asyncio
async def test_mount_prefers_existing_unity_equipment_image() -> None:
    urls: list[str] = []
    snapshot = replace(
        _asset_snapshot(),
        repositories={
            **_asset_snapshot().repositories,
            "mount": PublishedAssetRepository("example/seerapi", "b" * 40),
        },
    )

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(HTTP_OK, content=b"unity-mount")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=lambda: snapshot,
        )
        assert await source.fetch("mount", "1301170", fallback=False) == b"unity-mount"

    assert len(urls) == 1
    assert "seer-unity-assets" in urls[0]
    assert urls[0].endswith("/item/cloth/prev/1301170.png")


def test_manifest_backed_images_do_not_fall_back_to_mutable_main() -> None:
    assert asyncio.run(_fetch_without_asset_snapshot()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_status", [404, 410, 503])
async def test_strict_render_assets_retry_failure_without_caching_placeholder(
    tmp_path: Path,
    failure_status: int,
) -> None:
    urls: list[str] = []
    failing = True

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if request.url.host == "dummyimage.com":
            return httpx.Response(200, content=b"placeholder")
        return httpx.Response(failure_status if failing else 200, content=b"real-art")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        clients = HttpClients(cache=client, origin=client)
        store = SeerAssetStore(
            HttpSeerImageSource(clients, asset_snapshot_getter=_asset_snapshot),
            tmp_path,
            SeerAssetStoreLimits(1024, 1024 * 1024, 4, 0),
            spawn=TaskOwner().create,
        )
        # A permissive request can display a placeholder but cannot cache it.
        placeholder = await store.fetch("pet_head", "70")
        assert placeholder.startswith(b"\x89PNG\r\n\x1a\n")
        assert all("dummyimage.com" not in url for url in urls)
        assert not await asyncio.to_thread(lambda: list(tmp_path.rglob("*.bin")))
        urls.clear()
        with pytest.raises(ImageSourceError):
            await load_pet_image_assets(store, resource_ids=(70,), type_ids=())
        assert all("dummyimage.com" not in url for url in urls)
        failing = False
        assert await store.fetch("pet_head", "70") == b"real-art"
        recovered = await load_pet_image_assets(store, resource_ids=(70,), type_ids=())
        assert recovered.pet_heads == ((70, "data:image/png;base64,cmVhbC1hcnQ="),)
        request_count = len(urls)
        assert (
            await load_pet_image_assets(store, resource_ids=(70,), type_ids=())
            == recovered
        )
        assert len(urls) == request_count


@pytest.mark.asyncio
@pytest.mark.parametrize("permissive_first", [True, False])
async def test_shared_download_keeps_each_callers_fallback_policy(
    tmp_path: Path,
    *,
    permissive_first: bool,
) -> None:
    started, release, both_prepared = asyncio.Event(), asyncio.Event(), asyncio.Event()
    prepared = 0
    requests = 0
    policies = (permissive_first, not permissive_first)

    def snapshot() -> PublishedRenderAssetSnapshot:
        nonlocal prepared
        prepared += 1
        if prepared == len(policies):
            both_prepared.set()
        return _asset_snapshot()

    async def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        started.set()
        await release.wait()
        return httpx.Response(503)

    owner = TaskOwner()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = SeerAssetStore(
            HttpSeerImageSource(
                HttpClients(cache=client, origin=client),
                asset_snapshot_getter=snapshot,
            ),
            tmp_path,
            SeerAssetStoreLimits(1024, 1024 * 1024, 4, 0),
            spawn=owner.create,
        )
        tasks: list[asyncio.Task[bytes]] = []
        try:
            tasks.append(
                asyncio.create_task(
                    store.fetch("pet_head", "70", fallback=permissive_first)
                )
            )
            await asyncio.wait_for(started.wait(), timeout=5)
            tasks.append(
                asyncio.create_task(
                    store.fetch("pet_head", "70", fallback=not permissive_first)
                )
            )
            await asyncio.wait_for(both_prepared.wait(), timeout=5)
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            permissive, strict = results if permissive_first else results[::-1]
            assert isinstance(permissive, bytes)
            assert permissive.startswith(b"\x89PNG\r\n\x1a\n")
            assert isinstance(strict, ImageSourceError)
            assert requests == PINNED_ASSET_SOURCE_COUNT
            assert not await asyncio.to_thread(lambda: list(tmp_path.rglob("*.bin")))
        finally:
            release.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await owner.cancel_all()


@pytest.mark.asyncio
async def test_queued_asset_request_keeps_its_captured_revision(tmp_path: Path) -> None:
    current = _asset_snapshot()
    captured = asyncio.Event()
    urls: list[str] = []

    def snapshot() -> PublishedRenderAssetSnapshot:
        captured.set()
        return current

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, content=request.url.path.encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        store = SeerAssetStore(
            HttpSeerImageSource(
                HttpClients(cache=client, origin=client),
                asset_snapshot_getter=snapshot,
            ),
            tmp_path,
            SeerAssetStoreLimits(1024, 1024 * 1024, 1, 300),
            spawn=TaskOwner().create,
        )
        first = asyncio.create_task(store.fetch("pet_body", "70", fallback=False))
        await captured.wait()
        current = replace(
            current,
            repositories={
                "default": PublishedAssetRepository(
                    "Murmansk-Seer/seer-unity-assets", "b" * 40
                )
            },
            manifest_revision="assets-v3",
        )
        old = await first
        assert ("a" * 40).encode() in old
        new = await store.fetch("pet_body", "70", fallback=False)
        assert ("b" * 40).encode() in new
        assert old != new
        before_hit = len(urls)
        current = _asset_snapshot()
        assert await store.fetch("pet_body", "70", fallback=False) == old
        assert len(urls) == before_hit
