# SPDX-License-Identifier: MIT
"""Pure presentation for one lucky-skin-window result."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ironsbot.services.seer.render_paths import LUCKY_SKIN_WINDOW_TEMPLATE_PATH
from ironsbot.services.seer.skin_price import (
    format_skin_store_amount,
    skin_ticket_name,
    skin_ticket_summary,
)

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
    ticket_icon: str | None
    ticket_name: str | None
    diamond_icon: str | None
    ticket_num: int | None
    minimum_diamonds: int | None
    price_text: str | None
    ticket_text: str | None
    price_error: bool


@dataclass(frozen=True, slots=True)
class LuckySkinWindowRenderDocument:
    cards: tuple[LuckySkinWindowCard, ...]

    @property
    def templates(self) -> Mapping[str, object]:
        return MappingProxyType({"offers": self.cards})


def present_lucky_skin_window(
    offers: tuple[LuckySkinWindowOffer, ...],
    images_by_skin_id: Mapping[int, str],
    *,
    ticket_icons: Mapping[int, str],
    diamond_icon: str | None,
) -> LuckySkinWindowRenderDocument:
    """Prepare a card document without loading data or assets."""
    cards: list[LuckySkinWindowCard] = []
    for index, offer in enumerate(offers, start=1):
        price = offer.store_price
        valid_price = price is not None and price.price > 0
        minimum, ticket_text = (
            skin_ticket_summary(price, quantity_prefix="最多")
            if price is not None
            else (None, None)
        )
        cards.append(
            LuckySkinWindowCard(
                index=index,
                skin_id=offer.skin_id,
                name=offer.name,
                watched=offer.watched,
                image=images_by_skin_id.get(offer.skin_id),
                ticket_icon=ticket_icons.get(price.ticket_id)
                if price is not None
                else None,
                ticket_name=skin_ticket_name(price) if price is not None else None,
                diamond_icon=diamond_icon,
                ticket_num=price.ticket_num
                if price is not None and price.ticket_num > 0
                else None,
                minimum_diamonds=minimum,
                price_text=f"橱窗价 {format_skin_store_amount(price)}"
                if valid_price and price is not None
                else None,
                ticket_text=ticket_text,
                price_error=not valid_price,
            )
        )
    return LuckySkinWindowRenderDocument(tuple(cards))


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
