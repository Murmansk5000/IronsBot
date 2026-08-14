# SPDX-License-Identifier: MIT
"""Materialize lucky-window image assets before pure HTML presentation."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import suppress
from typing import TYPE_CHECKING

from ironsbot.integrations.seer_data.skin_image_resolution import (
    load_skin_image_resolutions,
)
from ironsbot.services.seer.images import ImageSourceError, to_data_uri
from ironsbot.services.seer.rendering.lucky_skin_window import (
    present_lucky_skin_window,
    render_lucky_skin_window_document,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.lucky_skin_window import (
        LuckySkinWindowOffer,
        LuckySkinWindowResult,
    )
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.render_coordinator import RenderCoordinator


async def render_lucky_skin_window(  # noqa: PLR0913 - composition dependencies
    cache: RenderCache,
    data: SeerDataAccess,
    images: SeerImageSource,
    coordinator: RenderCoordinator,
    result: LuckySkinWindowResult,
    offers: tuple[LuckySkinWindowOffer, ...],
) -> bytes:
    """Render one result while isolating missing skin art to its own card."""
    content_key = _cache_key(result, offers)
    if cached := cache.get("lucky_skin_window_v1", content_key):
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
    images_by_skin_id = dict(
        await asyncio.gather(
            *(
                _load_skin_image(
                    offer.skin_id,
                    resource_ids.get(offer.skin_id, offer.resource_id),
                    images,
                )
                for offer in offers
            )
        )
    )
    document = present_lucky_skin_window(offers, images_by_skin_id)
    rendered = await render_lucky_skin_window_document(coordinator.render, document)
    cache.put("lucky_skin_window_v1", content_key, rendered)
    return rendered


async def _load_skin_image(
    skin_id: int,
    resource_id: int,
    images: SeerImageSource,
) -> tuple[int, str]:
    if resource_id <= 0:
        return skin_id, ""
    with suppress(ImageSourceError):
        return skin_id, to_data_uri(
            await images.fetch("pet_body", str(resource_id), fallback=False)
        )
    return skin_id, ""


def _cache_key(
    result: LuckySkinWindowResult,
    offers: tuple[LuckySkinWindowOffer, ...],
) -> str:
    raw = "|".join(
        (
            result.day,
            str(result.player_id),
            *(
                f"{offer.skin_id}:{offer.resource_id}:{int(offer.watched)}"
                for offer in offers
            ),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
