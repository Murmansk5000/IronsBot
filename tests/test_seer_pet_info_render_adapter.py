# SPDX-License-Identifier: MIT
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.integrations.seer_data import pet_info_renderer
from ironsbot.services.seer.images import ImageSourceError
from ironsbot.services.seer.pet_info_views import (
    PetCoreSnapshot,
    PetDerivedDisplayData,
    PetInfoSnapshot,
    PetStatsSnapshot,
)
from ironsbot.services.seer.render_cache import RenderCacheEntry

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


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
        return b"image"


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
        activation_items=(),
        partner=None,
        skill_mintmarks=(),
        display=PetDerivedDisplayData((), (), ()),
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
    assert cache.values
    assert {category for category, _key in cache.values} == {"pet_info"}


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
            return b"image"

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
@pytest.mark.parametrize("missing_kind", ["pet_head", "pet_body"])
async def test_mandatory_failure_never_renders_or_caches(
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
            return b"image"

    async def unexpected_render(**_kwargs: Any) -> bytes:
        pytest.fail("mandatory asset failure must stop before rendering")

    with pytest.raises(ImageSourceError):
        await pet_info_renderer.render_published_pet_info(
            cast("RenderCache", cache),
            cast("SeerDataAccess", data),
            cast("SeerImageSource", Images()),
            cast("HtmlTemplateRenderer", unexpected_render),
            1,
        )
    assert not cache.values
