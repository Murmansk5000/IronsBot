# SPDX-License-Identifier: MIT
"""Render a four-column lucky skin window card."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, TypedDict

from ironsbot.services.seer.images import ImageSourceError, SeerImageSource, to_data_uri
from ironsbot.services.seer.render_paths import LUCKY_SKIN_WINDOW_TEMPLATE_PATH
from ironsbot.services.seer.skin_image_resolution import load_skin_image_resolutions
from ironsbot.services.seer.skin_price import FASHION_TICKET_VALUE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.lucky_skin_window import (
        LuckySkinWindowOffer,
        LuckySkinWindowResult,
    )
    from ironsbot.services.seer.render_cache import RenderCache

    from . import HtmlTemplateRenderer


class LuckySkinWindowCard(TypedDict):
    index: int
    skin_id: int
    name: str
    watched: bool
    image: str | None
    ticket_icon: str
    diamond_icon: str
    ticket_num: int | None
    minimum_diamonds: int | None
    price_text: str | None
    ticket_text: str | None
    price_error: bool


_FASHION_TICKET_ID = "1727935"
_DIAMOND_ICON_URL = (
    "https://raw.githubusercontent.com/Murmansk-Seer/seer-unity-assets/main/"
    "newseer/assets/art/ui/common/icon_diamond.png"
)
_CURRENCY_CACHE_CATEGORY = "lucky_skin_window_currency_v1"
_CARD_CACHE_CATEGORY = "lucky_skin_window_v5"
_TICKET_FALLBACK_ICON = to_data_uri(
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    b'<path fill="#f3b63e" '
    b'd="M6 17a7 7 0 0 0 7-7h38a7 7 0 0 0 7 7v30a7 7 0 0 0-7 7H13a7 7 0 0 0-7-7z"/>'
    b'<path fill="#fff0a6" d="M28 14h8v36h-8z"/>'
    b'<path fill="#d58826" d="M10 27h14v10H10zm30 0h14v10H40z"/>'
    b'</svg>',
    "image/svg+xml",
)
_DIAMOND_FALLBACK_ICON = to_data_uri(
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    b'<path fill="#68d9ff" d="M8 23 20 9h24l12 14-24 34z"/>'
    b'<path fill="#d6f7ff" d="m20 9 12 14L44 9z"/>'
    b'<path fill="#28a9e0" d="M8 23h24L20 9zm24 0h24L44 9zm0 34V23h24z"/>'
    b'</svg>',
    "image/svg+xml",
)

logger = logging.getLogger(__name__)


async def render_lucky_skin_window(  # noqa: PLR0913 - shared rendering dependencies
    cache: RenderCache,
    data: SeerDataAccess,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    result: LuckySkinWindowResult,
    offers: tuple[LuckySkinWindowOffer, ...],
) -> bytes:
    """Render today's four offers without letting one missing asset fail the card."""

    content_key = _cache_key(result, offers)
    if cached := cache.get(_CARD_CACHE_CATEGORY, content_key):
        return cached

    skin_ids = tuple(offer.skin_id for offer in offers)
    with data.query(
        lambda session: load_skin_image_resolutions(session, skin_ids)
    ) as resolutions:
        body_resource_ids = {
            skin_id: resolution.body_resource_id
            for skin_id, resolution in resolutions.items()
            if resolution.body_resource_id > 0
        }

    ticket_icon, diamond_icon = await _currency_icons(cache, images)
    cards = await asyncio.gather(
        *(
            _card(
                index,
                offer,
                images,
                body_resource_ids.get(offer.skin_id, offer.resource_id),
                ticket_icon,
                diamond_icon,
            )
            for index, offer in enumerate(offers, start=1)
        )
    )
    rendered = await render_html(
        template_path=LUCKY_SKIN_WINDOW_TEMPLATE_PATH,
        template_name="template.html.j2",
        templates={"offers": cards},
        max_width=1040,
        allow_refit=False,
    )
    cache.put(_CARD_CACHE_CATEGORY, content_key, rendered)
    return rendered


async def _card(  # noqa: PLR0913 - render context stays explicit
    index: int,
    offer: LuckySkinWindowOffer,
    images: SeerImageSource,
    body_resource_id: int,
    ticket_icon: str,
    diamond_icon: str,
) -> LuckySkinWindowCard:
    image: str | None = None
    if body_resource_id > 0:
        with suppress(ImageSourceError):
            image = to_data_uri(
                await images.fetch(
                    "pet_body",
                    str(body_resource_id),
                    fallback=False,
                )
            )
    price = offer.store_price
    ticket_num = (
        price.ticket_num
        if price is not None and price.ticket_num > 0
        else None
    )
    minimum_diamonds = (
        max(price.price - ticket_num * FASHION_TICKET_VALUE, 0)
        if price is not None and ticket_num is not None and price.price > 0
        else None
    )
    price_text = None
    ticket_text = None
    price_error = price is None or price.price <= 0
    if not price_error and price is not None:
        price_text = f"橱窗价 {price.price}钻"
        if price.original_price > 0 and price.original_price != price.price:
            price_text += f"（原价{price.original_price}钻）"
        if ticket_num is not None:
            discount = ticket_num * FASHION_TICKET_VALUE
            if discount < price.price:
                ticket_text = f"最多{ticket_num}张风尚券，最低{minimum_diamonds}钻"
            else:
                ticket_text = f"最多{ticket_num}张风尚券，可抵扣{discount}钻"
    return {
        "index": index,
        "skin_id": offer.skin_id,
        "name": offer.name,
        "watched": offer.watched,
        "image": image,
        "ticket_icon": ticket_icon,
        "diamond_icon": diamond_icon,
        "ticket_num": ticket_num,
        "minimum_diamonds": minimum_diamonds,
        "price_text": price_text,
        "ticket_text": ticket_text,
        "price_error": price_error,
    }


async def _currency_icons(
    cache: RenderCache,
    images: SeerImageSource,
) -> tuple[str, str]:
    ticket, diamond = await asyncio.gather(
        _cached_currency_icon(
            cache,
            "fashion_ticket",
            lambda: images.fetch("item", _FASHION_TICKET_ID, fallback=False),
            fallback=_TICKET_FALLBACK_ICON,
        ),
        _cached_currency_icon(
            cache,
            "diamond",
            lambda: images.fetch_url(_DIAMOND_ICON_URL),
            fallback=_DIAMOND_FALLBACK_ICON,
        ),
    )
    return ticket, diamond


async def _cached_currency_icon(
    cache: RenderCache,
    key: str,
    fetch: Callable[[], Awaitable[bytes]],
    *,
    fallback: str,
) -> str:
    if cached := cache.get(_CURRENCY_CACHE_CATEGORY, key):
        return to_data_uri(cached)
    try:
        data = await fetch()
    except ImageSourceError as error:
        logger.warning(
            "lucky skin window currency icon unavailable; using embedded fallback: "
            "currency=%s error=%s",
            key,
            error,
        )
        return fallback
    cache.put(_CURRENCY_CACHE_CATEGORY, key, data)
    return to_data_uri(data)


def _cache_key(
    result: LuckySkinWindowResult,
    offers: tuple[LuckySkinWindowOffer, ...],
) -> str:
    raw = "|".join(
        (
            result.day,
            str(result.player_id),
            *(
                f"{offer.skin_id}:{offer.resource_id}:{int(offer.watched)}:"
                f"{_price_cache_value(offer)}"
                for offer in offers
            ),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _price_cache_value(offer: LuckySkinWindowOffer) -> str:
    price = offer.store_price
    if price is None:
        return "missing"
    return ":".join(
        str(value)
        for value in (
            price.price,
            price.original_price,
            price.ticket_id,
            price.ticket_num,
            price.selected_price,
        )
    )
