# SPDX-License-Identifier: MIT
"""Materialize lucky-window image assets before pure HTML presentation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ironsbot.integrations.seer_data.skin_image_resolution import (
    load_skin_image_resolutions,
)
from ironsbot.services.seer.images import fetch_optional_image, to_data_uri
from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.rendering.lucky_skin_window import (
    present_lucky_skin_window,
    render_lucky_skin_window_document,
)
from ironsbot.services.seer.skin_price import skin_ticket_discount

_DIAMOND_ICON_KEY = "icon_diamond"
_CACHE_CATEGORY = "lucky_skin_window_v3"

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataReader
    from ironsbot.services.seer.images import ImageKind, SeerImageSource
    from ironsbot.services.seer.lucky_skin_window import (
        LuckySkinWindowOffer,
        LuckySkinWindowResult,
    )
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


async def render_lucky_skin_window(  # noqa: PLR0913 - composition dependencies
    cache: RenderCache,
    data: SeerDataReader,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    result: LuckySkinWindowResult,
    offers: tuple[LuckySkinWindowOffer, ...],
) -> bytes:
    """Render one result while isolating missing skin art to its own card."""
    content_key = render_request_cache_key(
        _CACHE_CATEGORY, (result.day, result.player_id, offers)
    )
    cache_entry = cache.entry(_CACHE_CATEGORY, content_key)
    if cached := cache_entry.get():
        return cached

    with data.query(
        lambda session: load_skin_image_resolutions(
            session,
            (offer.skin_id for offer in offers),
        )
    ) as resolutions:
        resource_ids = {
            skin_id: resolution.body_resource_id
            for skin_id, resolution in resolutions.items()
            if resolution.body_resource_id > 0
        }
    requested_ids = {
        offer.skin_id: resource_ids.get(offer.skin_id, offer.resource_id)
        for offer in offers
    }
    distinct_ids = sorted({id_ for id_ in requested_ids.values() if id_ > 0})
    ticket_ids = sorted(
        {
            offer.store_price.ticket_id
            for offer in offers
            if offer.store_price is not None
            and offer.store_price.price > 0
            and skin_ticket_discount(offer.store_price) is not None
        }
    )
    icon_requests: tuple[tuple[ImageKind, str], ...] = (
        (
            *(("item", str(ticket_id)) for ticket_id in ticket_ids),
            ("common", _DIAMOND_ICON_KEY),
        )
        if ticket_ids
        else ()
    )
    results = await asyncio.gather(
        *(fetch_optional_image(images, "pet_body", str(id_)) for id_ in distinct_ids),
        *(fetch_optional_image(images, kind, key) for kind, key in icon_requests),
    )
    body_results = results[: len(distinct_ids)]
    icon_results = results[len(distinct_ids) :]
    icons = {
        request: to_data_uri(result.data)
        for request, result in zip(icon_requests, icon_results, strict=True)
        if result.data
    }
    images_by_resource = {
        id_: to_data_uri(result.data)
        for id_, result in zip(distinct_ids, body_results, strict=True)
        if result.data
    }
    images_by_skin_id = {
        skin_id: images_by_resource.get(resource_id, "")
        for skin_id, resource_id in requested_ids.items()
    }
    document = present_lucky_skin_window(
        offers,
        images_by_skin_id,
        ticket_icons={
            ticket_id: icons["item", str(ticket_id)]
            for ticket_id in ticket_ids
            if ("item", str(ticket_id)) in icons
        },
        diamond_icon=icons.get(("common", _DIAMOND_ICON_KEY)),
    )
    rendered = await render_lucky_skin_window_document(render_html, document)
    if all(images_by_skin_id.values()) and all(result.data for result in icon_results):
        cache_entry.put(rendered)
    return rendered
