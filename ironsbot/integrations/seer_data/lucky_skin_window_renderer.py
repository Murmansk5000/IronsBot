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

_FASHION_TICKET_ID = "1727935"
_DIAMOND_ICON_KEY = "icon_diamond"
_CACHE_CATEGORY = "lucky_skin_window_v3"

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataReader
    from ironsbot.services.seer.images import SeerImageSource
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
    results = await asyncio.gather(
        *(fetch_optional_image(images, "pet_body", str(id_)) for id_ in distinct_ids),
        fetch_optional_image(images, "item", _FASHION_TICKET_ID),
        fetch_optional_image(images, "common", _DIAMOND_ICON_KEY),
    )
    body_results = results[: len(distinct_ids)]
    ticket_result, diamond_result = results[-2:]
    images_by_resource = {
        id_: to_data_uri(result.data)
        for id_, result in zip(distinct_ids, body_results, strict=True)
        if result.data
    }
    images_by_skin_id = {
        skin_id: images_by_resource.get(resource_id, "")
        for skin_id, resource_id in requested_ids.items()
    }
    ticket_icon = to_data_uri(ticket_result.data) if ticket_result.data else None
    diamond_icon = to_data_uri(diamond_result.data) if diamond_result.data else None
    document = present_lucky_skin_window(
        offers,
        images_by_skin_id,
        ticket_icon=ticket_icon,
        diamond_icon=diamond_icon,
    )
    rendered = await render_lucky_skin_window_document(render_html, document)
    if all(images_by_skin_id.values()) and ticket_icon and diamond_icon:
        cache_entry.put(rendered)
    return rendered
