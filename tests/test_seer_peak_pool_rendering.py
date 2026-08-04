# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.integrations.seer_data.peak_pool_renderer import render_peak_pool
from ironsbot.integrations.seer_data.peak_pool_vote_renderer import (
    render_peak_pool_vote,
)
from ironsbot.services.seer.peak import (
    PeakPetSnapshot,
    PeakPoolSnapshot,
    PeakVoteItemSnapshot,
    PeakVotePoolInput,
)
from ironsbot.services.seer.rendering.peak_pool import (
    peak_pool_cache_key,
    present_peak_pool,
)
from ironsbot.services.seer.rendering.peak_pool_vote import (
    peak_pool_vote_cache_key,
    present_peak_pool_vote,
)
from ironsbot.services.seer.rendering.pet_image_assets import PetImageAssets

if TYPE_CHECKING:
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


class _Cache:
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


def test_peak_pool_cache_key_changes_with_rendered_snapshot_fields() -> None:
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

    assert peak_pool_cache_key(original, "竞技池") != peak_pool_cache_key(
        changed,
        "竞技池",
    )


@pytest.mark.asyncio
async def test_peak_pool_adapter_skips_asset_loading_on_final_cache_hit() -> None:
    cache = _Cache(b"cached")

    result = await render_peak_pool(
        cast("RenderCache", cache),
        cast("SeerImageSource", _Images()),
        cast("HtmlTemplateRenderer", _unexpected_render),
        _pools(),
        "竞技池",
    )

    assert result == b"cached"


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
        ("peak_pool", peak_pool_cache_key(_pools(), "竞技池"), b"rendered")
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


def test_peak_vote_cache_key_changes_with_rendered_time() -> None:
    pools = _vote_pools()

    assert peak_pool_vote_cache_key(
        pools,
        "2026-08-05 12:00",
    ) != peak_pool_vote_cache_key(pools, "2026-08-05 12:01")


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
            peak_pool_vote_cache_key(_vote_pools(), generated_at),
            b"rendered-vote",
        )
    ]
