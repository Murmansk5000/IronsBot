# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from ironsbot.integrations.seer_data.lucky_skin_window_renderer import (
    render_lucky_skin_window,
)
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinWindowOffer,
    LuckySkinWindowResult,
)
from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.rendering.lucky_skin_window import (
    present_lucky_skin_window,
    render_lucky_skin_window_document,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.render_coordinator import RenderCoordinator
    from ironsbot.services.seer.rendering import TemplatePath

SKIN_ID = 101
RENDER_WIDTH = 1040


def test_lucky_skin_window_document_keeps_offer_identity_and_watch_state() -> None:
    document = present_lucky_skin_window(
        (
            LuckySkinWindowOffer(SKIN_ID, 1400101, "皮肤甲", watched=True),
            LuckySkinWindowOffer(102, 1400102, "皮肤乙", watched=False),
        ),
        {SKIN_ID: "data:image/png;base64,one"},
    )

    assert document.cards[0].skin_id == SKIN_ID
    assert document.cards[0].watched is True
    assert document.cards[0].image == "data:image/png;base64,one"
    assert document.cards[1].image is None


def test_lucky_skin_window_document_renders_the_prepared_view_model() -> None:
    document = present_lucky_skin_window(
        (LuckySkinWindowOffer(SKIN_ID, 1400101, "皮肤甲", watched=False),),
        {},
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


def test_lucky_window_request_key_tracks_actual_ordered_offers() -> None:
    first = LuckySkinWindowOffer(101, 1400101, "First", watched=False)
    second = LuckySkinWindowOffer(102, 1400102, "Second", watched=False)
    result = LuckySkinWindowResult("2026-09-12", 123456, (), from_cache=False)
    keys: list[str] = []

    class CacheHit:
        def get(self, category: str, key: str) -> bytes:
            assert category == "lucky_skin_window_v1"
            keys.append(key)
            return b"cached"

    def run(
        current: LuckySkinWindowResult,
        offers: tuple[LuckySkinWindowOffer, ...],
    ) -> None:
        # A cache hit must not touch any of these deliberately unusable adapters.
        assert asyncio.run(
            render_lucky_skin_window(
                cast("RenderCache", CacheHit()),
                cast("SeerDataAccess", object()),
                cast("SeerImageSource", object()),
                cast("RenderCoordinator", object()),
                current,
                offers,
            )
        ) == b"cached"

    original = (first, second)
    run(result, original)
    assert keys[0] == render_request_cache_key(
        "lucky_skin_window_v1", (result.day, result.player_id, original)
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
