# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
from typing import TYPE_CHECKING, Any, cast

import pytest
from PIL import Image, UnidentifiedImageError

from ironsbot.integrations.seer_data import pet_info_renderer
from ironsbot.services.seer.images import ImageSourceError
from ironsbot.services.seer.pet_info_views import (
    PetCoreSnapshot,
    PetDerivedDisplayData,
    PetInfoSnapshot,
    PetItemSnapshot,
    PetMintmarkSnapshot,
    PetSkillSnapshot,
    PetSoulmarkSnapshot,
    PetSpecialEffectView,
    PetStatsSnapshot,
    SoulmarkIconAsset,
)
from ironsbot.services.seer.render_cache import RenderCacheEntry

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


def _body_png() -> bytes:
    with Image.new("RGBA", (2, 1)) as image:
        image.putpixel((0, 0), (255, 0, 0, 64))
        image.putpixel((1, 0), (0, 0, 255, 192))
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def test_body_flip_preserves_source_and_alpha() -> None:
    original = _body_png()
    before = bytes(original)
    result = pet_info_renderer._flip_pet_body(original)
    assert original == before
    with Image.open(BytesIO(result)) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0)) == (0, 0, 255, 192)
        assert image.getpixel((1, 0)) == (255, 0, 0, 64)


def test_invalid_body_is_not_silently_accepted() -> None:
    with pytest.raises(UnidentifiedImageError):
        pet_info_renderer._flip_pet_body(b"invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt_body", [b"invalid", _body_png()[:45]])
async def test_corrupt_body_is_local_failure_not_whole_render_failure(
    monkeypatch: pytest.MonkeyPatch, corrupt_body: bytes
) -> None:
    data, cache = FakeData(), FakeCache()
    snapshot = replace(
        _snapshot(),
        skills=(
            PetSkillSnapshot(
                id=10,
                name="保留技能",
                type_id=1,
                type_name="普通",
                category_id=1,
                category_name="物理",
                power=80,
                max_pp=10,
                accuracy=100,
                crit_rate=None,
                priority=0,
                must_hit=False,
                info=None,
                learning_level=1,
                is_special=False,
                is_advanced=False,
                is_fifth=False,
                effects=(),
                friend_effects=(),
                activation_item_id=None,
                hide_effect_description=None,
            ),
        ),
    )
    monkeypatch.setattr(
        pet_info_renderer, "load_pet_info_snapshot", lambda *_: snapshot
    )
    head = _body_png()

    class Images:
        async def fetch(self, kind: str, _key: str, *, fallback: bool) -> bytes:
            assert fallback is False
            return corrupt_body if kind == "pet_body" else head

    captured: dict[str, Any] = {}
    failures: list[tuple[str, str, ImageSourceError]] = []

    async def render_html(**kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"rendered-with-placeholder"

    async def report(kind: str, key: str, error: ImageSourceError) -> None:
        failures.append((kind, key, error))

    result = await pet_info_renderer.render_published_pet_info(
        cast("RenderCache", cache),
        cast("SeerDataAccess", data),
        cast("SeerImageSource", Images()),
        cast("HtmlTemplateRenderer", render_html),
        1,
        image_failure_reporter=report,
    )
    assert result == b"rendered-with-placeholder"
    assert base64.b64decode(
        captured["pet_body_img"].split(",", 1)[1]
    ) == pet_info_renderer.placeholder_image("pet_body")
    assert base64.b64decode(captured["pet_head_img"].split(",", 1)[1]) == head
    assert captured["level_skills"][0]["name"] == "保留技能"
    assert len(failures) == 1
    assert failures[0][:2] == ("pet_body", "1001")
    assert isinstance(failures[0][2].__cause__, OSError)
    assert not cache.values


class FakeData:
    def __init__(self) -> None:
        self.session_active = False

    @contextmanager
    def query(self, operation: object) -> Iterator[PetInfoSnapshot | None]:
        self.session_active = True
        try:
            yield operation(object())  # type: ignore[operator]
        finally:
            self.session_active = False


class FakeImages:
    def __init__(self, data: FakeData) -> None:
        self._data = data

    async def fetch(self, *_args: object, **_kwargs: object) -> bytes:
        assert _kwargs.get("fallback") is False
        assert self._data.session_active is False
        return _body_png()


class FakeCache:
    def entry(self, category: str, key: str) -> RenderCacheEntry:
        return RenderCacheEntry(
            lambda: self.get(category, key),
            lambda data: self.put(category, key, data),
        )

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def get(self, category: str, content_key: str) -> bytes | None:
        return self.values.get((category, content_key))

    def put(self, category: str, content_key: str, data: bytes) -> None:
        self.values[(category, content_key)] = data


def _snapshot() -> PetInfoSnapshot:
    return PetInfoSnapshot(
        pet=PetCoreSnapshot(1, "测试精灵", 1001, 0, 1, "普通", ""),
        base_stats=PetStatsSnapshot(1, 1, 1, 1, 1, 1),
        advance_stats=None,
        skills=(),
        soulmarks=(),
        activation_items=(PetItemSnapshot(20, "测试道具", 1),),
        partner=None,
        skill_mintmarks=(PetMintmarkSnapshot(10, "测试刻印", "", ()),),
        display=PetDerivedDisplayData(
            (PetSpecialEffectView("测试状态", None, None, 30, ()),),
            (),
            (),
        ),
        rich_texts=(),
    )


@pytest.mark.asyncio
async def test_render_adapter_closes_sql_session_before_fetching_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = FakeData()
    cache = FakeCache()
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        pet_info_renderer,
        "load_pet_info_snapshot",
        lambda _session, _pet_id: _snapshot(),
    )
    monkeypatch.setattr(pet_info_renderer, "_load_gender_icon", lambda _gender: b"x")

    async def render_html(**kwargs: Any) -> bytes:
        assert data.session_active is False
        captured.update(kwargs)
        return b"rendered"

    result = await pet_info_renderer.render_published_pet_info(
        cast("RenderCache", cache),
        cast("SeerDataAccess", data),
        cast("SeerImageSource", FakeImages(data)),
        cast("HtmlTemplateRenderer", render_html),
        1,
    )

    assert result == b"rendered"
    assert captured["templates"]["pet_id"] == 1
    body = base64.b64decode(captured["templates"]["pet_body_img"].split(",", 1)[1])
    with Image.open(BytesIO(body)) as image:
        assert image.getpixel((0, 0)) == (0, 0, 255, 192)
        assert image.getpixel((1, 0)) == (255, 0, 0, 64)
    assert cache.values
    assert {category for category, _key in cache.values} == {"pet_info"}


@pytest.mark.asyncio
async def test_render_adapter_fetches_published_variant_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = FakeData()
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        display=replace(
            snapshot.display,
            special_effects=(
                PetSpecialEffectView("幽迹之秘", "说明", 545, None, (), "191_2"),
            ),
        ),
    )
    monkeypatch.setattr(
        pet_info_renderer, "load_pet_info_snapshot", lambda *_: snapshot
    )
    monkeypatch.setattr(pet_info_renderer, "_load_gender_icon", lambda _: b"x")
    requested: list[str] = []

    class Images:
        async def fetch(self, kind: str, key: str, *, fallback: bool) -> bytes:
            assert fallback is False
            if kind == "sign_buff":
                requested.append(key)
            return _body_png()

    captured: dict[str, Any] = {}

    async def render_html(**kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"rendered"

    await pet_info_renderer.render_published_pet_info(
        cast("RenderCache", FakeCache()),
        cast("SeerDataAccess", data),
        cast("SeerImageSource", Images()),
        cast("HtmlTemplateRenderer", render_html),
        1,
    )

    assert requested == ["191_2"]
    assert captured["templates"]["special_effects"][0]["icon"] is not None


@pytest.mark.asyncio
async def test_optional_failure_is_retried_before_final_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = FakeData()
    cache = FakeCache()
    monkeypatch.setattr(
        pet_info_renderer, "load_pet_info_snapshot", lambda *_: _snapshot()
    )
    monkeypatch.setattr(pet_info_renderer, "_load_gender_icon", lambda _: b"x")
    monkeypatch.setattr(pet_info_renderer, "_item_ids", lambda _: (123,))

    class RecoveringImages:
        failing = True
        calls = 0

        async def fetch(self, kind: object, *_args: object, **_kwargs: object) -> bytes:
            self.calls += 1
            if kind == "item" and self.failing:
                raise ImageSourceError
            return _body_png()

    images = RecoveringImages()
    rendered_count = 0

    async def render_html(**_kwargs: Any) -> bytes:
        nonlocal rendered_count
        rendered_count += 1
        return b"rendered"

    async def run() -> bytes:
        return await pet_info_renderer.render_published_pet_info(
            cast("RenderCache", cache),
            cast("SeerDataAccess", data),
            cast("SeerImageSource", images),
            cast("HtmlTemplateRenderer", render_html),
            1,
        )

    assert await run() == b"rendered"
    assert not cache.values
    images.failing = False
    assert await run() == b"rendered"
    assert cache.values
    calls = images.calls
    completed_renders = rendered_count
    assert await run() == b"rendered"
    assert images.calls == calls
    assert rendered_count == completed_renders


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing_kind",
    [
        "pet_head",
        "pet_body",
        "element_type",
        "mintmark",
        "item",
        "sign_buff",
    ],
)
async def test_asset_failure_uses_placeholder_without_caching(
    monkeypatch: pytest.MonkeyPatch,
    missing_kind: str,
) -> None:
    data, cache = FakeData(), FakeCache()
    monkeypatch.setattr(
        pet_info_renderer, "load_pet_info_snapshot", lambda *_: _snapshot()
    )

    class Images:
        async def fetch(self, kind: str, _key: str, *, fallback: bool) -> bytes:
            assert fallback is False
            if kind == missing_kind:
                raise ImageSourceError
            return _body_png()

    rendered: list[dict[str, Any]] = []
    reported: list[tuple[str, str, ImageSourceError]] = []

    async def render_html(**kwargs: Any) -> bytes:
        rendered.append(kwargs)
        return b"rendered-with-placeholder"

    async def report_failure(
        kind: str,
        key: str,
        error: ImageSourceError,
    ) -> None:
        reported.append((kind, key, error))

    result = await pet_info_renderer.render_published_pet_info(
        cast("RenderCache", cache),
        cast("SeerDataAccess", data),
        cast("SeerImageSource", Images()),
        cast("HtmlTemplateRenderer", render_html),
        1,
        image_failure_reporter=report_failure,
    )

    assert result == b"rendered-with-placeholder"
    assert rendered
    if missing_kind == "sign_buff":
        assert rendered[0]["templates"]["special_effects"][0]["icon"] is None
    if missing_kind == "pet_body":
        body = base64.b64decode(
            rendered[0]["templates"]["pet_body_img"].split(",", 1)[1]
        )
        assert body == pet_info_renderer.placeholder_image("pet_body")
    assert reported and reported[0][0] == missing_kind
    assert not cache.values


@pytest.mark.asyncio
@pytest.mark.parametrize("flash_png", [b"flash", None])
async def test_soulmark_icon_prefers_unity_and_retries_flash_fallback(
    monkeypatch: pytest.MonkeyPatch,
    flash_png: bytes | None,
) -> None:
    data, cache = FakeData(), FakeCache()
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        soulmarks=(
            PetSoulmarkSnapshot(
                id=7,
                desc="测试魂印",
                analyze_desc=None,
                formatting_adjustment=None,
                intensified=False,
                intensified_to_id=None,
                is_adv=False,
                pve_effective=None,
                tags=(),
            ),
        ),
        display=replace(
            snapshot.display,
            soulmark_icons=((7, SoulmarkIconAsset(42, flash_png, "image/png")),),
        ),
    )
    monkeypatch.setattr(
        pet_info_renderer, "load_pet_info_snapshot", lambda *_: snapshot
    )
    monkeypatch.setattr(pet_info_renderer, "_load_gender_icon", lambda _: b"x")

    class Images:
        def __init__(self) -> None:
            self.unity_available = False
            self.requests: list[tuple[object, object]] = []

        async def fetch(self, kind: object, key: object, *, fallback: bool) -> bytes:
            assert fallback is False
            self.requests.append((kind, key))
            if kind == "soulmark_icon":
                if not self.unity_available:
                    raise ImageSourceError
                return b"unity"
            return _body_png()

    images = Images()
    documents: list[dict[str, Any]] = []
    reported: list[tuple[str, str, ImageSourceError]] = []

    async def render_html(**kwargs: Any) -> bytes:
        documents.append(kwargs["templates"])
        return b"rendered"

    async def report_failure(kind: str, key: str, error: ImageSourceError) -> None:
        reported.append((kind, key, error))

    async def render() -> bytes:
        return await pet_info_renderer.render_published_pet_info(
            cast("RenderCache", cache),
            cast("SeerDataAccess", data),
            cast("SeerImageSource", images),
            cast("HtmlTemplateRenderer", render_html),
            1,
            image_failure_reporter=report_failure,
        )

    assert await render() == b"rendered"
    assert ("soulmark_icon", "42") in images.requests
    fallback_icon = documents[-1]["soulmarks"][0]["icon"]
    if flash_png is None:
        assert fallback_icon.startswith("data:image/png;base64,")
        assert reported and reported[0][:2] == ("soulmark_icon", "42")
    else:
        assert fallback_icon == "data:image/png;base64,Zmxhc2g="
        assert not reported
    assert not cache.values

    images.unity_available = True
    assert await render() == b"rendered"
    assert documents[-1]["soulmarks"][0]["icon"] == ("data:image/png;base64,dW5pdHk=")
    assert cache.values
