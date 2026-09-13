# SPDX-License-Identifier: MIT
"""Pure presentation for one lucky-skin-window result."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ironsbot.services.seer.render_paths import LUCKY_SKIN_WINDOW_TEMPLATE_PATH
from ironsbot.services.seer.skin_price import format_lucky_window_price_lines

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowOffer

    from . import HtmlTemplateRenderer


@dataclass(frozen=True, slots=True)
class LuckySkinWindowCard:
    index: int
    skin_id: int
    name: str
    watched: bool
    image: str | None
    price_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LuckySkinWindowRenderDocument:
    cards: tuple[LuckySkinWindowCard, ...]

    @property
    def templates(self) -> Mapping[str, object]:
        return MappingProxyType({"offers": self.cards})


def present_lucky_skin_window(
    offers: tuple[LuckySkinWindowOffer, ...],
    images_by_skin_id: Mapping[int, str],
) -> LuckySkinWindowRenderDocument:
    """Prepare a card document without loading data or assets."""
    return LuckySkinWindowRenderDocument(
        tuple(
            LuckySkinWindowCard(
                index=index,
                skin_id=offer.skin_id,
                name=offer.name,
                watched=offer.watched,
                image=images_by_skin_id.get(offer.skin_id),
                price_lines=format_lucky_window_price_lines(offer.store_price),
            )
            for index, offer in enumerate(offers, start=1)
        )
    )


async def render_lucky_skin_window_document(
    render_html: HtmlTemplateRenderer,
    document: LuckySkinWindowRenderDocument,
) -> bytes:
    return await render_html(
        template_path=LUCKY_SKIN_WINDOW_TEMPLATE_PATH,
        template_name="template.html.j2",
        templates=document.templates,
        max_width=1040,
        allow_refit=False,
    )
