# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.integrations.seer_data.lucky_skin_window_renderer import (
    render_lucky_skin_window,
)
from ironsbot.integrations.seer_data.skin_image_resolution import SkinImageResolution
from ironsbot.integrations.storage.render_cache import FileRenderCache
from ironsbot.services.seer.images import ImageSourceError
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinWindowOffer,
    LuckySkinWindowResult,
)
from ironsbot.services.seer.render_cache import RenderCacheEntry
from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.rendering.lucky_skin_window import (
    present_lucky_skin_window,
    render_lucky_skin_window_document,
)
from ironsbot.services.seer.skin_price import SkinStorePrice

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from typing import Any

    from ironsbot.services.seer.data import SeerDataReader
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer, TemplatePath

SKIN_ID = 101
RENDER_WIDTH = 1040
EXPECTED_TICKET_NUM = 3
EXPECTED_MINIMUM_DIAMONDS = 150


def test_lucky_skin_window_document_keeps_offer_identity_and_watch_state() -> None:
    price = SkinStorePrice(
        skin_id=SKIN_ID,
        pool_id=1,
        price=180,
        original_price=200,
        discount_rate=0,
        selected_price=0,
        ticket_id=1,
        ticket_num=3,
        start_time=0,
        end_time=0,
    )
    document = present_lucky_skin_window(
        (
            LuckySkinWindowOffer(
                SKIN_ID,
                1400101,
                "皮肤甲",
                watched=True,
                store_price=price,
            ),
            LuckySkinWindowOffer(102, 1400102, "皮肤乙", watched=False),
        ),
        {SKIN_ID: "data:image/png;base64,one"},
        ticket_icon="data:image/png;base64,ticket",
        diamond_icon="data:image/png;base64,diamond",
    )

    assert document.cards[0].skin_id == SKIN_ID
    assert document.cards[0].watched is True
    assert document.cards[0].image == "data:image/png;base64,one"
    assert document.cards[0].price_text == "橱窗价 180钻（原价200钻）"
    assert document.cards[0].ticket_text == "最多3张风尚券，最低150钻"
    assert document.cards[0].price_error is False
    assert document.cards[0].ticket_icon == "data:image/png;base64,ticket"
    assert document.cards[0].diamond_icon == "data:image/png;base64,diamond"
    assert document.cards[0].ticket_num == EXPECTED_TICKET_NUM
    assert document.cards[0].minimum_diamonds == EXPECTED_MINIMUM_DIAMONDS
    assert document.cards[1].image is None
    assert document.cards[1].price_text is None
    assert document.cards[1].ticket_text is None
    assert document.cards[1].price_error is True


@pytest.mark.asyncio
async def test_window_uses_reader_mapping_and_preserves_four_offer_inputs(
    tmp_path: Path,
) -> None:
    query_open = False
    calls: list[str] = []
    cards: list[Any] = []

    class Data:
        @contextmanager
        def query(self, _operation: object) -> Iterator[dict[int, SkinImageResolution]]:
            nonlocal query_open
            query_open = True
            try:
                yield {101: SkinImageResolution(101, 1, 999, "test", "test", None)}
            finally:
                query_open = False

    class Images:
        async def fetch(self, _kind: str, key: str, *, fallback: bool) -> bytes:
            assert not query_open
            assert not fallback
            calls.append(key)
            return b"art"

    async def render_html(
        template_path: TemplatePath,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        cards.extend(templates["offers"])
        return b"rendered"

    offers = tuple(
        LuckySkinWindowOffer(id_, 1400000 + id_, f"Offer {id_}", watched=id_ == SKIN_ID)
        for id_ in range(101, 105)
    )
    result = LuckySkinWindowResult("2026-09-12", 123456, offers, from_cache=True)
    cache = FileRenderCache(
        tmp_path / "renders", 1024, version_getter=lambda: "release"
    )
    rendered = await render_lucky_skin_window(
        cache.bind("release", lambda _: False),
        cast("SeerDataReader", Data()),
        cast("SeerImageSource", Images()),
        render_html,
        result,
        offers,
    )
    assert rendered == b"rendered"
    assert calls == [
        "999",
        "1400102",
        "1400103",
        "1400104",
        "1727935",
        "icon_diamond",
    ]
    assert [(card.skin_id, card.name, card.watched) for card in cards] == [
        (offer.skin_id, offer.name, offer.watched) for offer in offers
    ]
    assert not (tmp_path / "renders").exists()


def test_lucky_skin_window_document_renders_the_prepared_view_model() -> None:
    document = present_lucky_skin_window(
        (LuckySkinWindowOffer(SKIN_ID, 1400101, "皮肤甲", watched=False),),
        {},
        ticket_icon=None,
        diamond_icon=None,
    )
    calls: list[dict[str, object]] = []

    async def render_html(
        template_path: TemplatePath,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        calls.append(
            {
                "template_path": template_path,
                "template_name": template_name,
                "templates": templates,
                "max_width": max_width,
                "allow_refit": allow_refit,
            }
        )
        return b"rendered"

    rendered = asyncio.run(render_lucky_skin_window_document(render_html, document))
    assert rendered == b"rendered"
    assert calls[0]["templates"] == document.templates
    assert calls[0]["max_width"] == RENDER_WIDTH


def test_lucky_window_template_uses_font_safe_watch_marker_and_currency_icons() -> None:
    template = (
        Path("ironsbot/services/seer/rendering/templates/lucky_skin_window")
        / "template.html.j2"
    ).read_text(encoding="utf-8")

    assert "⭐" not in template
    assert "★" in template
    assert 'class="currency"' in template
    assert "offer.diamond_icon" in template
    assert ".panel { width: 100%; padding: 22px 22px 16px; }" in template
    assert "height: 220px" in template
    assert "min-height: 66px" in template
    assert "橱窗价格数据异常" in template


def test_lucky_window_request_key_tracks_actual_ordered_offers() -> None:
    first = LuckySkinWindowOffer(101, 1400101, "First", watched=False)
    second = LuckySkinWindowOffer(102, 1400102, "Second", watched=False)
    result = LuckySkinWindowResult("2026-09-12", 123456, (), from_cache=False)
    keys: list[str] = []

    class CacheHit:
        def entry(self, category: str, key: str) -> RenderCacheEntry:
            return RenderCacheEntry(lambda: self.get(category, key), lambda _data: None)

        def get(self, category: str, key: str) -> bytes:
            assert category == "lucky_skin_window_v3"
            keys.append(key)
            return b"cached"

    def run(
        current: LuckySkinWindowResult,
        offers: tuple[LuckySkinWindowOffer, ...],
    ) -> None:
        # A cache hit must not touch any of these deliberately unusable adapters.
        assert (
            asyncio.run(
                render_lucky_skin_window(
                    cast("RenderCache", CacheHit()),
                    cast("SeerDataReader", object()),
                    cast("SeerImageSource", object()),
                    cast("HtmlTemplateRenderer", object()),
                    current,
                    offers,
                )
            )
            == b"cached"
        )

    original = (first, second)
    run(result, original)
    assert keys[0] == render_request_cache_key(
        "lucky_skin_window_v3", (result.day, result.player_id, original)
    )
    run(replace(result, from_cache=True), original)
    assert keys.pop() == keys[0]
    run(replace(result, day="2026-09-13"), original)
    run(replace(result, player_id=654321), original)
    run(result, (second, first))
    run(result, (first,))
    for changed in (
        replace(first, name="Renamed"),
        replace(first, resource_id=1400103),
        replace(first, skin_id=103),
        replace(first, watched=True),
    ):
        run(result, (changed, second))
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("resource_id", [0, 1400101])
def test_lucky_window_does_not_cache_missing_art(resource_id: int) -> None:
    class Cache:
        def entry(self, category: str, key: str) -> RenderCacheEntry:
            return RenderCacheEntry(
                lambda: self.get(category, key),
                lambda data: self.put(category, key, data),
            )

        value: bytes | None = None

        def get(self, *_: object) -> bytes | None:
            return self.value

        def put(self, _category: str, _key: str, value: bytes) -> None:
            self.value = value

    class Data:
        def query(self, _operation: object) -> nullcontext[dict[int, object]]:
            return nullcontext({})

    class Images:
        failing = True
        calls = 0

        async def fetch(self, _kind: str, _key: str, *, fallback: bool) -> bytes:
            assert fallback is False
            self.calls += 1
            if self.failing:
                raise ImageSourceError
            return b"image"

    class Renderer:
        async def render(self, **_kwargs: object) -> bytes:
            return b"rendered"

    cache, images = Cache(), Images()
    offers = (
        LuckySkinWindowOffer(101, resource_id, "First", watched=False),
        LuckySkinWindowOffer(102, resource_id, "Second", watched=True),
    )
    result = LuckySkinWindowResult("2026-09-12", 123456, offers, from_cache=False)

    def run() -> bytes:
        return asyncio.run(
            render_lucky_skin_window(
                cast("RenderCache", cache),
                cast("SeerDataReader", Data()),
                cast("SeerImageSource", images),
                cast("HtmlTemplateRenderer", Renderer().render),
                result,
                offers,
            )
        )

    assert run() == b"rendered"
    assert cache.value is None
    requests_per_render = 2 + int(resource_id > 0)
    assert images.calls == requests_per_render
    images.failing = False
    assert run() == b"rendered"
    assert (cache.value is not None) == (resource_id > 0)
    calls = images.calls
    assert run() == b"rendered"
    assert images.calls == calls + (0 if resource_id > 0 else requests_per_render)
