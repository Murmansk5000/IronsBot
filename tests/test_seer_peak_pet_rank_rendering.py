# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.integrations.seer_data.peak_pet_rank_renderer import (
    render_peak_pet_rank,
)
from ironsbot.services.seer.peak import (
    PeakPetBanSnapshot,
    PeakPetPickSnapshot,
    PeakPetRankRenderInput,
    PeakPetSnapshot,
)
from ironsbot.services.seer.rendering.peak_pet_rank import (
    peak_pet_rank_cache_key,
    present_peak_pet_rank,
)
from ironsbot.services.seer.rendering.pet_image_assets import PetImageAssets

if TYPE_CHECKING:
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


_EXPECTED_WIN_RATE = 60.0


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


def _input() -> PeakPetRankRenderInput:
    return PeakPetRankRenderInput(
        title="竞技精灵总榜",
        pick_items=(PeakPetPickSnapshot(id=7, count=10, win=6),),
        ban_items=(
            PeakPetBanSnapshot(id=8, name="盖亚", score=100),
            PeakPetBanSnapshot(id=99, name="未收录", score=80),
        ),
        pets=(
            PeakPetSnapshot(id=7, name="雷伊", resource_id=70, type_id=1),
            PeakPetSnapshot(id=8, name="盖亚", resource_id=71, type_id=2),
        ),
    )


def test_peak_pet_rank_presentation_uses_prepared_assets() -> None:
    document = present_peak_pet_rank(
        _input(),
        PetImageAssets(
            pet_heads=((70, "rei"), (71, "gaiya")),
            type_icons=((1, "electric"), (2, "fight")),
        ),
    )

    assert document.pick_ranks[0].name == "雷伊"
    assert document.pick_ranks[0].win_rate == _EXPECTED_WIN_RATE
    assert document.ban_ranks[0].head_img == "gaiya"
    assert document.ban_ranks[1].name == "未收录"
    assert document.ban_ranks[1].type_icon == ""


def test_peak_pet_rank_cache_key_changes_with_rendered_data() -> None:
    original = _input()
    changed = PeakPetRankRenderInput(
        title=original.title,
        pick_items=(PeakPetPickSnapshot(id=7, count=11, win=6),),
        ban_items=original.ban_items,
        pets=original.pets,
    )

    assert peak_pet_rank_cache_key(original) != peak_pet_rank_cache_key(changed)


@pytest.mark.asyncio
async def test_peak_pet_rank_adapter_skips_assets_on_final_cache_hit() -> None:
    result = await render_peak_pet_rank(
        cast("RenderCache", _Cache(b"cached")),
        cast("SeerImageSource", _Images()),
        cast("HtmlTemplateRenderer", _unexpected_render),
        _input(),
    )

    assert result == b"cached"


@pytest.mark.asyncio
async def test_peak_pet_rank_adapter_deduplicates_assets_and_writes_cache() -> None:
    cache = _Cache()
    images = _Images()
    captured: dict[str, Any] = {}

    async def render_html(**kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"rendered"

    result = await render_peak_pet_rank(
        cast("RenderCache", cache),
        cast("SeerImageSource", images),
        cast("HtmlTemplateRenderer", render_html),
        _input(),
    )

    assert result == b"rendered"
    assert images.requests == [
        ("pet_head", "70"),
        ("pet_head", "71"),
        ("element_type", "1"),
        ("element_type", "2"),
    ]
    assert captured["templates"]["title"] == "竞技精灵总榜"
    assert cache.writes == [
        ("peak_pet_rank", peak_pet_rank_cache_key(_input()), b"rendered")
    ]


async def _unexpected_render(**_kwargs: object) -> bytes:
    raise AssertionError
