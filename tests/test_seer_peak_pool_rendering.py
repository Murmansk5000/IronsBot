from __future__ import annotations

import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from ironsbot.core import time
from ironsbot.services.seer.peak import (
    PeakPetSnapshot,
    PeakPoolRenderSnapshot,
    PeakPoolSnapshot,
    PeakPoolTransitionSnapshot,
)
from ironsbot.services.seer.rendering.peak_pool import render_peak_pool

EXPECTED_RENDER_COUNT = 2
RGBA_CHANNEL_COUNT = 4


def _test_png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (2, 2), (80, 160, 240, 192)).save(output, format="PNG")
    return output.getvalue()


class _Cache:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def get(self, namespace: str, key: str) -> bytes | None:
        return self.values.get((namespace, key))

    def put(self, namespace: str, key: str, value: bytes) -> None:
        self.values[(namespace, key)] = value


class _Images:
    async def fetch(
        self,
        kind: str,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        del kind, key, fallback
        return _test_png()


def _data_uri_pixel(value: str) -> tuple[int, int, int, int]:
    data = base64.b64decode(value.partition(",")[2])
    with Image.open(BytesIO(data)) as image:
        pixel = image.convert("RGBA").getpixel((0, 0))
    if not isinstance(pixel, tuple) or len(pixel) != RGBA_CHANNEL_COUNT:
        raise AssertionError(pixel)
    return (int(pixel[0]), int(pixel[1]), int(pixel[2]), int(pixel[3]))


def _pool(*pets: PeakPetSnapshot, count: int = 0) -> PeakPoolSnapshot:
    return PeakPoolSnapshot(
        id=count + 1,
        count=count,
        start_time=datetime(2026, 8, 1, tzinfo=time.TZ_CN),
        end_time=datetime(2026, 8, 31, tzinfo=time.TZ_CN),
        pets=tuple(pets),
    )


@pytest.mark.asyncio
async def test_standard_pool_renders_current_and_historical_positions() -> None:
    moved = PeakPetSnapshot(1, "迁移精灵", 1001, 4)
    removed = PeakPetSnapshot(2, "移出精灵", 1002, 5)
    snapshot = PeakPoolRenderSnapshot(
        pools=(_pool(moved, count=0),),
        transitions=(
            PeakPoolTransitionSnapshot(moved, 2, 0),
            PeakPoolTransitionSnapshot(removed, 3, None),
        ),
        change_state="changed",
        content_version="20260814:2026-08-14",
        expert=False,
    )
    captured: dict[str, Any] = {}

    async def render_html(*_args: object, **kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"pool-image"

    result = await render_peak_pool(
        _Cache(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        snapshot,
        "竞技池 / 2026-08-01 ~ 2026-08-31",
    )

    assert result == b"pool-image"
    pools = {pool["label"]: pool for pool in captured["pools"]}
    assert tuple(pools) == ("限0", "限2", "限3", "不限")
    assert [(pet["id"], pet["historical"]) for pet in pools["限0"]["pets"]] == [
        (1, False)
    ]
    assert [(pet["id"], pet["historical"]) for pet in pools["限2"]["pets"]] == [
        (1, True)
    ]
    assert [(pet["id"], pet["historical"]) for pet in pools["限3"]["pets"]] == [
        (2, True)
    ]
    assert [(pet["id"], pet["historical"]) for pet in pools["不限"]["pets"]] == [
        (2, False)
    ]
    current_pixel = _data_uri_pixel(pools["限0"]["pets"][0]["head_img"])
    historical_pixel = _data_uri_pixel(pools["限2"]["pets"][0]["head_img"])
    assert current_pixel == (80, 160, 240, 192)
    assert historical_pixel == (56, 76, 96, 192)


@pytest.mark.asyncio
async def test_expert_pool_uses_only_disabled_and_unlimited_sections() -> None:
    entered = PeakPetSnapshot(1, "新禁用", 1001, 4)
    snapshot = PeakPoolRenderSnapshot(
        pools=(_pool(entered),),
        transitions=(PeakPoolTransitionSnapshot(entered, None, 0),),
        change_state="changed",
        content_version="20260814:2026-08-14",
        expert=True,
    )
    captured: dict[str, Any] = {}

    async def render_html(*_args: object, **kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"expert-image"

    await render_peak_pool(
        _Cache(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        snapshot,
        "专家禁用池 / 2026-08-01 ~ 2026-08-31",
    )

    pools = {pool["label"]: pool for pool in captured["pools"]}
    assert tuple(pools) == ("禁用", "不限")
    assert pools["禁用"]["pets"][0]["historical"] is False
    assert pools["不限"]["pets"][0]["historical"] is True
    assert (
        pools["禁用"]["pets"][0]["head_img"]
        != pools["不限"]["pets"][0]["head_img"]
    )


@pytest.mark.asyncio
async def test_pool_cache_key_changes_with_weekly_content_version() -> None:
    pet = PeakPetSnapshot(1, "测试精灵", 1001, 4)
    cache = _Cache()
    renders = 0

    async def render_html(*_args: object, **_kwargs: Any) -> bytes:
        nonlocal renders
        renders += 1
        return f"render-{renders}".encode()

    for version in ("20260814:first", "20260814:second"):
        await render_peak_pool(
            cache,  # type: ignore[arg-type]
            _Images(),  # type: ignore[arg-type]
            render_html,  # type: ignore[arg-type]
            PeakPoolRenderSnapshot(
                pools=(_pool(pet),),
                transitions=(),
                change_state="unchanged",
                content_version=version,
                expert=False,
            ),
            "竞技池",
        )

    assert renders == EXPECTED_RENDER_COUNT


def test_pool_template_avoids_unsupported_css_filters_and_arrows() -> None:
    template = (
        Path(__file__).parents[1]
        / "ironsbot/services/seer/rendering/templates/peak_pool/template.html.j2"
    ).read_text(encoding="utf-8")

    assert "filter:" not in template
    assert "opacity:" not in template
    assert "<strong>灰暗</strong>：上周所在位置" in template
    assert "transition-arrow" not in template
    assert "→" not in template
