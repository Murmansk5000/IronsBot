# SPDX-License-Identifier: MIT
"""Render a four-column lucky skin window card."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import suppress
from typing import TYPE_CHECKING, TypedDict

from ironsbot.services.seer.images import ImageSourceError, SeerImageSource, to_data_uri
from ironsbot.services.seer.render_paths import LUCKY_SKIN_WINDOW_TEMPLATE_PATH
from ironsbot.services.seer.skin_image_resolution import load_skin_image_resolutions

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.lucky_skin_window import (
        LuckySkinWindowOffer,
        LuckySkinWindowResult,
    )
    from ironsbot.services.seer.render_cache import RenderCache

    from . import HtmlTemplateRenderer


class LuckySkinWindowCard(TypedDict):
    skin_id: int
    name: str
    watched: bool
    image: str | None


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
    if cached := cache.get("lucky_skin_window_v1", content_key):
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

    cards = await asyncio.gather(
        *(
            _card(
                offer,
                images,
                body_resource_ids.get(offer.skin_id, offer.resource_id),
            )
            for offer in offers
        )
    )
    rendered = await render_html(
        template_path=LUCKY_SKIN_WINDOW_TEMPLATE_PATH,
        template_name="template.html.j2",
        templates={"offers": cards},
        max_width=1040,
        allow_refit=False,
    )
    cache.put("lucky_skin_window_v1", content_key, rendered)
    return rendered


async def _card(
    offer: LuckySkinWindowOffer,
    images: SeerImageSource,
    body_resource_id: int,
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
    return {
        "skin_id": offer.skin_id,
        "name": offer.name,
        "watched": offer.watched,
        "image": image,
    }


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
