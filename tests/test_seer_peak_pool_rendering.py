# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import os
from datetime import datetime, timezone
from io import BytesIO
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.integrations.seer_data.peak_pool_renderer import render_peak_pool
from ironsbot.integrations.seer_data.peak_pool_vote_renderer import (
    render_peak_pool_vote,
)
from ironsbot.services.seer.images import to_data_uri
from ironsbot.services.seer.peak import (
    PeakPetSnapshot,
    PeakPoolSnapshot,
    PeakVoteItemSnapshot,
    PeakVotePoolInput,
)
from ironsbot.services.seer.render_cache import RenderCacheEntry
from ironsbot.services.seer.rendering.cache_key import (
    render_document_cache_key,
    render_request_cache_key,
)
from ironsbot.services.seer.rendering.peak_pool import (
    present_peak_pool,
)
from ironsbot.services.seer.rendering.peak_pool_vote import (
    present_peak_pool_vote,
)
from ironsbot.services.seer.rendering.pet_image_assets import PetImageAssets

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


class _Cache:
    def entry(self, category: str, key: str) -> RenderCacheEntry:
        return RenderCacheEntry(
            lambda: self.get(category, key),
            lambda data: self.put(category, key, data),
        )

    def __init__(self, value: bytes | None = None) -> None:
        self.value = value
        self.writes: list[tuple[str, str, bytes]] = []

    def get(self, _category: str, _key: str) -> bytes | None:
        return self.value

    def put(self, category: str, key: str, data: bytes) -> None:
        self.writes.append((category, key, data))


class _Images:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    async def fetch(self, kind: str, key: str, **_kwargs: object) -> bytes:
        assert _kwargs.get("fallback") is False
        self.requests.append((kind, key))
        return f"{kind}:{key}".encode()


def _pet(
    id_: int,
    name: str,
    resource_id: int,
    type_id: int,
) -> PeakPetSnapshot:
    return PeakPetSnapshot(
        id=id_,
        name=name,
        resource_id=resource_id,
        type_id=type_id,
    )


def _asset_uri(kind: str, key: str) -> str:
    return to_data_uri(f"{kind}:{key}".encode())


def _pools() -> tuple[PeakPoolSnapshot, ...]:
    return (
        PeakPoolSnapshot(
            id=1,
            count=2,
            start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 8, tzinfo=timezone.utc),
            pets=(_pet(100, "雷伊", 70, 1), _pet(101, "盖亚", 71, 2)),
        ),
        PeakPoolSnapshot(
            id=2,
            count=3,
            start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 8, tzinfo=timezone.utc),
            pets=(_pet(102, "缪斯", 70, 1),),
        ),
    )


def test_peak_pool_presentation_uses_preloaded_assets() -> None:
    document = present_peak_pool(
        _pools(),
        "竞技池",
        PetImageAssets(
            pet_heads=((70, "rei"), (71, "gaiya")),
            type_icons=((1, "electric"), (2, "fight")),
        ),
    )

    assert document.pool_type == "竞技池"
    assert document.pools[0].pets[0].head_img == "rei"
    assert document.pools[0].pets[1].type_icon == "fight"
    assert document.max_width > 0


def test_peak_pool_document_key_changes_with_rendered_snapshot_fields() -> None:
    original = _pools()
    changed = (
        PeakPoolSnapshot(
            id=1,
            count=2,
            start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 8, tzinfo=timezone.utc),
            pets=(_pet(100, "雷神", 70, 1), _pet(101, "盖亚", 71, 2)),
        ),
        original[1],
    )

    assets = PetImageAssets(
        pet_heads=((70, "rei"), (71, "gaiya")),
        type_icons=((1, "electric"), (2, "fight")),
    )
    assert render_document_cache_key(
        present_peak_pool(original, "竞技池", assets)
    ) != render_document_cache_key(present_peak_pool(changed, "竞技池", assets))


@pytest.mark.asyncio
async def test_peak_pool_adapter_checks_final_cache_before_loading_assets() -> None:
    cache = _Cache(b"cached")
    images = _Images()

    result = await render_peak_pool(
        cast("RenderCache", cache),
        cast("SeerImageSource", images),
        cast("HtmlTemplateRenderer", _unexpected_render),
        _pools(),
        "竞技池",
    )

    assert result == b"cached"
    assert images.requests == []


@pytest.mark.asyncio
async def test_peak_pool_adapter_deduplicates_assets_and_writes_final_cache() -> None:
    cache = _Cache()
    images = _Images()
    captured: dict[str, Any] = {}

    async def render_html(**kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"rendered"

    result = await render_peak_pool(
        cast("RenderCache", cache),
        cast("SeerImageSource", images),
        cast("HtmlTemplateRenderer", render_html),
        _pools(),
        "竞技池",
    )

    assert result == b"rendered"
    assert images.requests == [
        ("pet_head", "70"),
        ("pet_head", "71"),
        ("element_type", "1"),
        ("element_type", "2"),
    ]
    assert captured["templates"]["pool_type"] == "竞技池"
    assert cache.writes == [
        (
            "peak_pool",
            render_request_cache_key("peak_pool", ("竞技池", _pools())),
            b"rendered",
        )
    ]


async def _unexpected_render(**_kwargs: object) -> bytes:
    raise AssertionError


def _vote_pools() -> tuple[PeakVotePoolInput, ...]:
    return (
        PeakVotePoolInput(
            title="限2池票选",
            items=(
                PeakVoteItemSnapshot(id=100, name="旧名", score=123),
                PeakVoteItemSnapshot(id=999, name="未收录", score=100),
            ),
            pets=(_pet(100, "雷伊", 70, 1),),
        ),
    )


def test_peak_vote_presentation_uses_snapshot_and_fallback_name() -> None:
    document = present_peak_pool_vote(
        _vote_pools(),
        "2026-08-05 12:00",
        PetImageAssets(pet_heads=((70, "rei"),), type_icons=((1, "electric"),)),
    )

    assert document.pools[0].ranks[0].name == "雷伊"
    assert document.pools[0].ranks[0].head_img == "rei"
    assert document.pools[0].ranks[1].name == "未收录"
    assert document.pools[0].ranks[1].type_icon == ""


def test_peak_vote_document_key_changes_with_rendered_time() -> None:
    pools = _vote_pools()
    assets = PetImageAssets(pet_heads=((70, "rei"),), type_icons=((1, "electric"),))

    assert render_document_cache_key(
        present_peak_pool_vote(pools, "2026-08-05 12:00", assets)
    ) != render_document_cache_key(
        present_peak_pool_vote(pools, "2026-08-05 12:01", assets)
    )


@pytest.mark.asyncio
async def test_peak_vote_adapter_deduplicates_assets_and_writes_final_cache() -> None:
    cache = _Cache()
    images = _Images()
    captured: dict[str, Any] = {}

    async def render_html(**kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"rendered-vote"

    generated_at = "2026-08-05 12:00"
    result = await render_peak_pool_vote(
        cast("RenderCache", cache),
        cast("SeerImageSource", images),
        cast("HtmlTemplateRenderer", render_html),
        _vote_pools(),
        generated_at,
    )

    assert result == b"rendered-vote"
    assert images.requests == [("pet_head", "70"), ("element_type", "1")]
    assert captured["templates"]["generated_at"] == generated_at
    assert cache.writes == [
        (
            "peak_pool_vote",
            render_request_cache_key(
                "peak_pool_vote",
                (generated_at, _vote_pools()),
            ),
            b"rendered-vote",
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["pool", "vote", "rank"])
@pytest.mark.parametrize("failure", [404, 503, "timeout"])
@pytest.mark.parametrize("complete", [True, False])
async def test_peak_adapters_recover_without_caching_failed_images(  # noqa: C901, PLR0915 - shared adapter/backend matrix
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    failure: int | str,
    *,
    complete: bool,
) -> None:
    """Use synthetic HTTP PNGs; opt in to native HTML via the render-test env."""
    from httpx import AsyncClient, MockTransport, ReadTimeout, Request, Response
    from PIL import Image

    from ironsbot.app.lifecycle import TaskOwner
    from ironsbot.integrations.htmlkit import render_html_template
    from ironsbot.integrations.http.clients import HttpClients
    from ironsbot.integrations.http.seer_images import HttpSeerImageSource
    from ironsbot.integrations.seer_data.peak_pet_rank_renderer import (
        render_peak_pet_rank,
    )
    from ironsbot.integrations.storage.render_cache import FileRenderCache
    from ironsbot.integrations.storage.seer_assets import (
        SeerAssetStore,
        SeerAssetStoreLimits,
    )
    from ironsbot.services.seer.images import (
        ImageSourceError,
        PublishedRenderAssetSnapshot,
    )
    from ironsbot.services.seer.peak import PeakPetPickSnapshot, PeakPetRankRenderInput
    from ironsbot.services.seer.render_coordinator import RenderCoordinator

    native = os.environ.get("IRONSBOT_NATIVE_RENDER_TESTS") == "1"
    if native:
        import nonebot

        try:
            driver = nonebot.get_driver()
        except ValueError:
            nonebot.init()
            driver = nonebot.get_driver()
        if fontconfig := os.environ.get("IRONSBOT_RENDER_FONTCONFIG"):
            monkeypatch.setattr(
                driver.config, "fontconfig_file", fontconfig, raising=False
            )
        from nonebot_plugin_htmlkit import init_fontconfig

        init_fontconfig()

    output = BytesIO()
    Image.new("RGB", (96, 96), "#159ca8").save(output, format="PNG")
    asset = output.getvalue()
    requests: list[str] = []
    broken = True
    renders = 0
    revision = "1" * 40
    publication = PublishedRenderAssetSnapshot(
        "example/assets", revision, "manifest", frozenset()
    )
    raw_revision = f"/example/assets/{revision}/"
    cdn_revision = f"/gh/example/assets@{revision}/"

    def transport(request: Request) -> Response:
        requests.append(str(request.url))
        assert raw_revision in request.url.path or cdn_revision in request.url.path
        if broken:
            if failure == "timeout":
                raise ReadTimeout(str(request.url), request=request)
            return Response(int(failure))
        return Response(200, content=asset, headers={"content-type": "image/png"})

    async def render_html(*args: Any, **kwargs: Any) -> bytes:
        nonlocal renders
        renders += 1
        if native:
            return await render_html_template(*args, **kwargs)
        return asset

    owner = TaskOwner()
    cache_dir = tmp_path / "renders"
    cache = FileRenderCache(
        cache_dir,
        8 * 1024 * 1024,
        version_getter=lambda: "release-1",
        category_available=lambda _category: complete,
    )
    coordinator = RenderCoordinator(render_html, timeout_seconds=20)
    try:
        async with AsyncClient(transport=MockTransport(transport)) as client:
            images = SeerAssetStore(
                HttpSeerImageSource(
                    HttpClients(cache=client, origin=client),
                    asset_snapshot_getter=lambda: publication,
                ),
                tmp_path / "assets",
                SeerAssetStoreLimits(1024 * 1024, 8 * 1024 * 1024, 1, 0),
                spawn=owner.create,
            )

            async def request_image() -> bytes:
                if mode == "pool":
                    return await render_peak_pool(
                        cache, images, coordinator.render, _pools(), "竞技池"
                    )
                if mode == "vote":
                    return await render_peak_pool_vote(
                        cache,
                        images,
                        coordinator.render,
                        _vote_pools(),
                        "2026-09-12 14:00",
                    )
                return await render_peak_pet_rank(
                    cache,
                    images,
                    coordinator.render,
                    PeakPetRankRenderInput(
                        "竞技精灵总榜",
                        "2026-09-12 14:00",
                        (PeakPetPickSnapshot(100, 10, 6),),
                        (),
                        _pools()[0].pets,
                    ),
                )

            with pytest.raises(ImageSourceError):
                await request_image()
            assert renders == 0
            assert not list(cache_dir.rglob("*.bin"))
            failed_requests = len(requests)
            broken = False
            rendered = await request_image()
            assert renders == 1
            assert len(requests) > failed_requests
            cold_requests = list(requests)
            cold_renders = renders
            assert bool(list(cache_dir.rglob("*.bin"))) is complete
            assert await request_image() == rendered
            assert requests == cold_requests
            assert renders == cold_renders + (not complete)
            with Image.open(BytesIO(rendered)) as image:
                assert image.format == "PNG"
                if native:
                    minimum_side, minimum_colors = 200, 100
                    assert min(image.size) >= minimum_side
                    colors = image.convert("RGB").getcolors(image.width * image.height)
                    assert colors is not None and len(colors) > minimum_colors
            if native:
                (tmp_path / f"{mode}.png").write_bytes(rendered)
    finally:
        await owner.cancel_all()
