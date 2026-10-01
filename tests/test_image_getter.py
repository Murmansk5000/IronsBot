# SPDX-License-Identifier: MIT
import asyncio
import hashlib
import json
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
    ImageKind,
    ImageSourceError,
    PublishedAssetRepository,
    PublishedRenderAssetSnapshot,
)

HTTP_NOT_FOUND = 404
HTTP_OK = 200
MAX_ASSET_FETCH_CONCURRENCY = 4
PINNED_ASSET_SOURCE_COUNT = 2
CNB_SOURCE_COUNT = 3
CNB_LFS_SOURCE_COUNT = 5
PNG_DATA = b"\x89PNG\r\n\x1a\nverified-image"


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


def _git_blob(data: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(data)}\0".encode() + data, usedforsecurity=False
    ).hexdigest()


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


async def _fetch_soulmark_icon() -> tuple[bytes, list[str]]:
    cache = _ItemFallbackClient()
    clients = HttpClients(cache=cache)
    images = HttpSeerImageSource(clients, asset_snapshot_getter=_asset_snapshot)
    try:
        return await images.fetch("soulmark_icon", "42", fallback=False), cache.urls
    finally:
        await clients.close()


async def _fetch_battle_effect() -> tuple[bytes, list[str]]:
    cache = _ItemFallbackClient()
    clients = HttpClients(cache=cache)
    images = HttpSeerImageSource(clients, asset_snapshot_getter=_asset_snapshot)
    try:
        return await images.fetch("battle_effect", "19", fallback=False), cache.urls
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


def test_soulmark_icon_uses_unity_effect_icon_asset() -> None:
    data, urls = asyncio.run(_fetch_soulmark_icon())

    assert data == b"item-image"
    assert urls == [
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/"
        "newseer/assets/art/ui/assets/effecticon/42.png"
    ]


def test_battle_effect_image_uses_the_published_asset_revision() -> None:
    data, urls = asyncio.run(_fetch_battle_effect())

    assert data == b"item-image"
    assert urls == [
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/"
        "newseer/assets/art/ui/assets/battleeffect/abnormal/19.png"
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
@pytest.mark.parametrize(
    ("kind", "cnb_path"),
    [
        ("battle_effect", "battleeffect_abnormal/19.png"),
        ("mintmark", "countermark_icon/12001.png"),
        ("pet_head", "defaultpackage_assets_art_ui_assets_pet_head/12001.png"),
        ("sign_buff", "battleeffect_signbuff/19.png"),
        ("soulmark_icon", "effecticon/19.png"),
        (
            "suit",
            "defaultpackage_assets_art_ui_assets_item_cloth_suiticon/12001.png",
        ),
    ],
)
async def test_matching_cnb_images_back_up_transient_primary_failures(
    kind: ImageKind, cnb_path: str
) -> None:
    urls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(
            200 if request.url.host == "cnb.cool" else 503,
            content=PNG_DATA if request.url.host == "cnb.cool" else b"",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=_asset_snapshot,
            asset_blob_getter=lambda _kind, _key, _snapshot: _git_blob(PNG_DATA),
        )
        key = "12001" if "12001" in cnb_path else "19"
        assert await source.fetch(kind, key, fallback=False) == PNG_DATA

    assert len(urls) == CNB_SOURCE_COUNT
    assert urls[2].startswith("https://cnb.cool/HurryWang/seer-unity-suit-assets/")
    assert "/-/git/raw/main/" in urls[2]
    assert urls[2].endswith(f"/imgs/{cnb_path}")


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_status", [200, 404])
async def test_cnb_is_not_used_for_success_or_missing_primary(
    primary_status: int,
) -> None:
    urls: list[str] = []
    blob_requests: list[str] = []

    def published_blob(
        _kind: ImageKind, key: str, _snapshot: PublishedRenderAssetSnapshot
    ) -> str:
        blob_requests.append(key)
        return _git_blob(PNG_DATA)

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(primary_status, content=PNG_DATA)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=_asset_snapshot,
            asset_blob_getter=published_blob,
        )
        if primary_status == HTTP_OK:
            assert await source.fetch("pet_head", "12001", fallback=False) == PNG_DATA
        else:
            with pytest.raises(ImageSourceError):
                await source.fetch("pet_head", "12001", fallback=False)

    assert len(urls) == (1 if primary_status == HTTP_OK else 2)
    assert all("cnb.cool" not in url for url in urls)
    assert blob_requests == []


@pytest.mark.asyncio
async def test_cnb_requires_a_published_blob() -> None:
    urls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=_asset_snapshot,
        )
        with pytest.raises(ImageSourceError):
            await source.fetch("mintmark", "12001", fallback=False)

    assert len(urls) == PINNED_ASSET_SOURCE_COUNT
    assert all("cnb.cool" not in url for url in urls)


@pytest.mark.asyncio
async def test_cnb_rejects_stale_bytes_from_another_release() -> None:
    urls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(
            200 if request.url.host == "cnb.cool" else 503,
            content=PNG_DATA if request.url.host == "cnb.cool" else b"",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=_asset_snapshot,
            asset_blob_getter=lambda _kind, _key, _snapshot: _git_blob(
                PNG_DATA + b"new"
            ),
        )
        with pytest.raises(ImageSourceError, match="503"):
            await source.fetch("pet_head", "3488", fallback=False)

    assert len(urls) == CNB_SOURCE_COUNT


@pytest.mark.asyncio
@pytest.mark.parametrize("published_blob", ["image", "pointer"])
async def test_cnb_pet_body_resolves_and_verifies_lfs_pointer(
    published_blob: str,
) -> None:
    oid = hashlib.sha256(PNG_DATA).hexdigest()
    pointer = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{oid}\nsize {len(PNG_DATA)}\n"
    ).encode()
    urls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if request.url.host in {"raw.githubusercontent.com", "cdn.jsdelivr.net"}:
            return httpx.Response(503)
        if request.method == "POST":
            assert request.headers["content-type"] == "application/vnd.git-lfs+json"
            payload = json.loads(request.content)
            assert payload["objects"] == [{"oid": oid, "size": len(PNG_DATA)}]
            return httpx.Response(
                200,
                json={
                    "objects": [
                        {
                            "actions": {
                                "download": {
                                    "href": "https://lfs.cnb.cool/lfs/objects/test"
                                }
                            }
                        }
                    ]
                },
            )
        if request.url.host == "lfs.cnb.cool":
            return httpx.Response(200, content=PNG_DATA)
        return httpx.Response(200, content=pointer)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=_asset_snapshot,
            asset_blob_getter=lambda _kind, _key, _snapshot: _git_blob(
                pointer if published_blob == "pointer" else PNG_DATA
            ),
        )
        assert await source.fetch("pet_body", "12001", fallback=False) == PNG_DATA

    assert len(urls) == CNB_LFS_SOURCE_COUNT
    assert "/-/git/raw/master/" in urls[2]
    assert "/imgs/pet_body/12001.png" in urls[2]
    assert urls[3].endswith("/info/lfs/objects/batch")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["mintmark", "pet_body"])
async def test_cnb_rejects_invalid_image_and_lfs_bytes(kind: ImageKind) -> None:
    oid = hashlib.sha256(PNG_DATA).hexdigest()
    pointer = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{oid}\nsize {len(PNG_DATA)}\n"
    ).encode()
    cnb_data = pointer if kind == "pet_body" else b"<html>error</html>"
    urls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if request.url.host in {"raw.githubusercontent.com", "cdn.jsdelivr.net"}:
            return httpx.Response(503)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "objects": [
                        {
                            "actions": {
                                "download": {
                                    "href": "https://lfs.cnb.cool/lfs/objects/test"
                                }
                            }
                        }
                    ]
                },
            )
        if request.url.host == "lfs.cnb.cool":
            return httpx.Response(200, content=PNG_DATA + b"changed")
        return httpx.Response(200, content=cnb_data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=_asset_snapshot,
            asset_blob_getter=lambda _kind, _key, _snapshot: _git_blob(cnb_data),
        )
        with pytest.raises(ImageSourceError):
            await source.fetch(kind, "12001", fallback=False)
    assert any("cnb.cool" in url for url in urls)


@pytest.mark.asyncio
async def test_cnb_lfs_malformed_response_preserves_primary_failure() -> None:
    pointer = (
        f"version https://git-lfs.github.com/spec/v1\noid sha256:{'a' * 64}\nsize 12\n"
    ).encode()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host in {"raw.githubusercontent.com", "cdn.jsdelivr.net"}:
            return httpx.Response(503)
        if request.method == "POST":
            return httpx.Response(200, content=b"invalid-json")
        return httpx.Response(200, content=pointer)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=_asset_snapshot,
            asset_blob_getter=lambda _kind, _key, _snapshot: _git_blob(pointer),
        )
        with pytest.raises(ImageSourceError, match="503"):
            await source.fetch("pet_body", "12001", fallback=False)


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
        "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/"
        f"{'a' * 40}/newseer/assets/art/ui/assets/item/cloth/icon/1301170.png",
        "https://cdn.jsdelivr.net/gh/Murmansk-Seer/seer-unity-assets@"
        f"{'a' * 40}/newseer/assets/art/ui/assets/item/cloth/icon/1301170.png",
        "https://raw.githubusercontent.com/example/seerapi/"
        f"{'b' * 40}/mount/1301170.png",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "key", "suffix"),
    [
        ("autocard_card", "card_7", "/autocard/texture/cards/card_7.png"),
        ("autocard_chip", "autocardChip_115", "/autocard/s2chip/autocardChip_115.png"),
        (
            "autocard_role",
            "role_9",
            "/autocard/texture/roles/card/role_9.png",
        ),
    ],
)
async def test_autocard_uses_the_published_asset_revision(
    kind: str,
    key: str,
    suffix: str,
) -> None:
    urls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(HTTP_OK, content=b"autocard")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=_asset_snapshot,
        )
        assert await source.fetch(kind, key, fallback=False) == b"autocard"  # type: ignore[arg-type]

    assert len(urls) == 1
    assert f"/{'a' * 40}/" in urls[0]
    assert urls[0].endswith(suffix)


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
