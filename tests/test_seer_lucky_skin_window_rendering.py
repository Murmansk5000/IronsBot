# SPDX-License-Identifier: MIT
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinWindowOffer,
    LuckySkinWindowResult,
)
from ironsbot.services.seer.rendering import lucky_skin_window as rendering
from ironsbot.services.seer.rendering.lucky_skin_window import (
    render_lucky_skin_window,
)
from ironsbot.services.seer.skin_price import SkinStorePrice

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


_WATCHED_SKIN_ID = 2
_RENDER_WIDTH = 1040
_EXPECTED_CACHE_ENTRIES = 3


class _Cache:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, str], bytes] = {}

    def get(self, category: str, key: str) -> bytes | None:
        return self.entries.get((category, key))

    def put(self, category: str, key: str, data: bytes) -> None:
        self.entries[(category, key)] = data


class _Data:
    @contextmanager
    def query(self, operation: object) -> Iterator[object]:
        yield operation(object())  # type: ignore[operator]


class _Images:
    def __init__(self, *, missing: set[str] | None = None) -> None:
        self.missing = missing or set()
        self.requests: list[tuple[str, str]] = []

    async def fetch(
        self,
        kind: str,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        del fallback
        self.requests.append((kind, key))
        if key in self.missing:
            from ironsbot.services.seer.images import ImageSourceError

            raise ImageSourceError("missing")
        return f"{kind}:{key}".encode()

    async def fetch_url(self, url: str) -> bytes:
        self.requests.append(("url", url))
        if url in self.missing:
            from ironsbot.services.seer.images import ImageSourceError

            raise ImageSourceError("missing")
        return f"url:{url}".encode()


def _result() -> LuckySkinWindowResult:
    return LuckySkinWindowResult(
        day="2026-08-14",
        player_id=123456,
        offers=tuple(
            LuckySkinWindowOffer(
                skin_id=index,
                resource_id=1_400_000 + index,
                name=f"皮肤 {index}",
                watched=index == _WATCHED_SKIN_ID,
                store_price=SkinStorePrice(
                    skin_id=index,
                    pool_id=1,
                    price=298,
                    original_price=398,
                    discount_rate=0,
                    selected_price=0,
                    ticket_id=1_727_935,
                    ticket_num=20,
                    start_time=0,
                    end_time=0,
                ),
            )
            for index in range(1, 5)
        ),
        from_cache=False,
    )


@pytest.mark.asyncio
async def test_render_lucky_skin_window_uses_four_full_portraits_and_watch_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        captured.update(
            template_path=template_path,
            template_name=template_name,
            templates=templates,
            max_width=max_width,
            allow_refit=allow_refit,
        )
        return b"lucky-window-image"

    monkeypatch.setattr(
        rendering,
        "load_skin_image_resolutions",
        lambda _session, skin_ids: {
            skin_id: SimpleNamespace(body_resource_id=9_000 + skin_id)
            for skin_id in skin_ids
        },
    )
    images = _Images()
    cache = _Cache()
    result = _result()

    rendered = await render_lucky_skin_window(
        cache,  # type: ignore[arg-type]
        _Data(),  # type: ignore[arg-type]
        images,  # type: ignore[arg-type]
        render_html,
        result,
        result.offers,
    )

    assert rendered == b"lucky-window-image"
    assert captured["max_width"] == _RENDER_WIDTH
    assert captured["allow_refit"] is False
    cards = captured["templates"]["offers"]
    assert [card["skin_id"] for card in cards] == [1, 2, 3, 4]
    assert [card["name"] for card in cards] == ["皮肤 1", "皮肤 2", "皮肤 3", "皮肤 4"]
    assert [card["watched"] for card in cards] == [False, True, False, False]
    assert all(card["image"].startswith("data:image/png;base64,") for card in cards)
    assert [card["ticket_num"] for card in cards] == [20, 20, 20, 20]
    assert [card["minimum_diamonds"] for card in cards] == [98, 98, 98, 98]
    assert all(card["ticket_icon"] for card in cards)
    assert all(card["diamond_icon"] for card in cards)
    assert images.requests[:2] == [
        ("item", "1727935"),
        ("url", rendering._DIAMOND_ICON_URL),
    ]
    assert images.requests[2:] == [
        ("pet_body", str(9_000 + index)) for index in range(1, 5)
    ]
    assert len(cache.entries) == _EXPECTED_CACHE_ENTRIES


@pytest.mark.asyncio
async def test_render_lucky_skin_window_uses_icons_when_remote_currency_assets_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        captured.update(templates)
        return b"lucky-window-image"

    monkeypatch.setattr(
        rendering,
        "load_skin_image_resolutions",
        lambda _session, skin_ids: {
            skin_id: SimpleNamespace(body_resource_id=9_000 + skin_id)
            for skin_id in skin_ids
        },
    )
    result = _result()
    images = _Images(
        missing={rendering._FASHION_TICKET_ID, rendering._DIAMOND_ICON_URL}
    )

    await render_lucky_skin_window(
        _Cache(),  # type: ignore[arg-type]
        _Data(),  # type: ignore[arg-type]
        images,  # type: ignore[arg-type]
        render_html,
        result,
        result.offers,
    )

    cards = captured["offers"]
    assert all(
        card["ticket_icon"].startswith("data:image/svg+xml;base64,")
        for card in cards
    )
    assert all(
        card["diamond_icon"].startswith("data:image/svg+xml;base64,")
        for card in cards
    )


@pytest.mark.asyncio
async def test_render_lucky_skin_window_keeps_other_offers_when_one_portrait_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        captured.update(templates)
        return b"lucky-window-image"

    monkeypatch.setattr(
        rendering,
        "load_skin_image_resolutions",
        lambda _session, skin_ids: {
            skin_id: SimpleNamespace(body_resource_id=9_000 + skin_id)
            for skin_id in skin_ids
        },
    )
    result = _result()
    await render_lucky_skin_window(
        _Cache(),  # type: ignore[arg-type]
        _Data(),  # type: ignore[arg-type]
        _Images(missing={"9003"}),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        result,
        result.offers,
    )

    cards = captured["offers"]
    assert [card["image"] is None for card in cards] == [False, False, True, False]


@pytest.mark.asyncio
async def test_render_lucky_skin_window_marks_missing_store_prices_as_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        captured.update(templates)
        return b"lucky-window-image"

    monkeypatch.setattr(
        rendering,
        "load_skin_image_resolutions",
        lambda _session, skin_ids: {
            skin_id: SimpleNamespace(body_resource_id=9_000 + skin_id)
            for skin_id in skin_ids
        },
    )
    result = _result()
    missing_price = LuckySkinWindowResult(
        day=result.day,
        player_id=result.player_id,
        offers=(
            result.offers[0],
            result.offers[1],
            LuckySkinWindowOffer(
                skin_id=3,
                resource_id=1_400_003,
                name="皮肤 3",
                watched=False,
            ),
            result.offers[3],
        ),
        from_cache=False,
    )

    await render_lucky_skin_window(
        _Cache(),  # type: ignore[arg-type]
        _Data(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        render_html,
        missing_price,
        missing_price.offers,
    )

    cards = captured["offers"]
    assert cards[2]["price_error"]
    assert cards[2]["price_text"] is None
