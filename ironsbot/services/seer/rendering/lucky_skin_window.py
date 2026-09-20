# SPDX-License-Identifier: MIT
"""Pure presentation for one lucky-skin-window result."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ironsbot.services.seer.render_paths import LUCKY_SKIN_WINDOW_TEMPLATE_PATH
from ironsbot.services.seer.skin_price import FASHION_TICKET_VALUE

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
    ticket_icon: str | None,
    diamond_icon: str | None,
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
                ticket_icon=ticket_icon,
                diamond_icon=diamond_icon,
                ticket_num=_ticket_num(offer),
                minimum_diamonds=_minimum_diamonds(offer),
                price_text=_price_text(offer),
                ticket_text=_ticket_text(offer),
                price_error=offer.store_price is None or offer.store_price.price <= 0,
            )
            for index, offer in enumerate(offers, start=1)
        )
    )


def _ticket_num(offer: LuckySkinWindowOffer) -> int | None:
    price = offer.store_price
    return price.ticket_num if price is not None and price.ticket_num > 0 else None


def _minimum_diamonds(offer: LuckySkinWindowOffer) -> int | None:
    price = offer.store_price
    if price is None or price.price <= 0:
        return None
    ticket_num = _ticket_num(offer)
    if ticket_num is None:
        return None
    return max(price.price - ticket_num * FASHION_TICKET_VALUE, 0)


def _price_text(offer: LuckySkinWindowOffer) -> str | None:
    price = offer.store_price
    if price is None or price.price <= 0:
        return None
    text = f"橱窗价 {price.price}钻"
    if price.original_price > 0 and price.original_price != price.price:
        text += f"（原价{price.original_price}钻）"
    return text


def _ticket_text(offer: LuckySkinWindowOffer) -> str | None:
    price = offer.store_price
    ticket_num = _ticket_num(offer)
    minimum_diamonds = _minimum_diamonds(offer)
    if price is None or ticket_num is None or minimum_diamonds is None:
        return None
    discount = ticket_num * FASHION_TICKET_VALUE
    if discount < price.price:
        return f"最多{ticket_num}张风尚券，最低{minimum_diamonds}钻"
    return f"最多{ticket_num}张风尚券，可抵扣{discount}钻"


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
