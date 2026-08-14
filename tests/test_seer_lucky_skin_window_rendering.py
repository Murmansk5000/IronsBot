# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio

from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowOffer
from ironsbot.services.seer.rendering.lucky_skin_window import (
    present_lucky_skin_window,
    render_lucky_skin_window_document,
)

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

    async def render_html(**kwargs: object) -> bytes:
        calls.append(kwargs)
        return b"rendered"

    rendered = asyncio.run(render_lucky_skin_window_document(render_html, document))
    assert rendered == b"rendered"
    assert calls[0]["templates"] == document.templates
    assert calls[0]["max_width"] == RENDER_WIDTH
