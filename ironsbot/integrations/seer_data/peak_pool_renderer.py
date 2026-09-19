# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose peak-pool snapshots, assets, cache, and the HTML render port."""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageEnhance, ImageOps

from ironsbot.services.seer.images import to_data_uri
from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.rendering.peak_pool import (
    PeakPoolImageAssets,
    present_peak_pool,
    render_peak_pool_document,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.peak import PeakPoolRenderSnapshot
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer

_CACHE_CATEGORY = "peak_pool"


async def render_peak_pool(
    cache: RenderCache,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    snapshot: PeakPoolRenderSnapshot,
    pool_type: str,
) -> bytes:
    """Render current and historical pool positions from one immutable snapshot."""
    request_key = render_request_cache_key(_CACHE_CATEGORY, (pool_type, snapshot))
    cache_entry = cache.entry(_CACHE_CATEGORY, request_key)
    if cached := cache_entry.get():
        return cached
    assets = await _load_peak_pool_image_assets(images, snapshot)
    document = present_peak_pool(snapshot, pool_type, assets)
    rendered = await render_peak_pool_document(render_html, document)
    cache_entry.put(rendered)
    return rendered


async def _load_peak_pool_image_assets(
    images: SeerImageSource,
    snapshot: PeakPoolRenderSnapshot,
) -> PeakPoolImageAssets:
    pets = {
        pet.id: pet
        for pet in (
            *(pet for pool in snapshot.pools for pet in pool.pets),
            *(transition.pet for transition in snapshot.transitions),
        )
    }
    resource_ids = tuple(sorted({pet.resource_id for pet in pets.values()}))
    type_ids = tuple(sorted({pet.type_id for pet in pets.values() if pet.type_id > 0}))
    fetched = await asyncio.gather(
        *(
            images.fetch("pet_head", str(resource_id), fallback=False)
            for resource_id in resource_ids
        ),
        *(
            images.fetch("element_type", str(type_id), fallback=False)
            for type_id in type_ids
        ),
    )
    head_values = fetched[: len(resource_ids)]
    type_values = fetched[len(resource_ids) :]
    historical_resource_ids = {
        transition.pet.resource_id for transition in snapshot.transitions
    }
    historical_ids = tuple(
        resource_id
        for resource_id in resource_ids
        if resource_id in historical_resource_ids
    )
    head_by_resource_id = dict(zip(resource_ids, head_values, strict=True))
    dimmed_values = await asyncio.gather(
        *(
            asyncio.to_thread(
                _dim_historical_head,
                head_by_resource_id[resource_id],
            )
            for resource_id in historical_ids
        )
    )
    dimmed_by_resource_id = dict(zip(historical_ids, dimmed_values, strict=True))
    return PeakPoolImageAssets(
        heads=tuple(
            (resource_id, to_data_uri(value))
            for resource_id, value in zip(resource_ids, head_values, strict=True)
        ),
        historical_heads=tuple(
            (
                resource_id,
                to_data_uri(dimmed_by_resource_id.get(resource_id, value)),
            )
            for resource_id, value in zip(
                resource_ids,
                head_values,
                strict=True,
            )
        ),
        type_icons=tuple(
            (type_id, to_data_uri(value))
            for type_id, value in zip(type_ids, type_values, strict=True)
        ),
    )


def _dim_historical_head(data: bytes) -> bytes:
    try:
        with Image.open(BytesIO(data)) as source:
            rgba = source.convert("RGBA")
        alpha = rgba.getchannel("A")
        rgb = rgba.convert("RGB")
        grayscale = ImageOps.grayscale(rgb).convert("RGB")
        dimmed = ImageEnhance.Brightness(Image.blend(rgb, grayscale, 0.75)).enhance(0.5)
        dimmed.putalpha(alpha)
        output = BytesIO()
        dimmed.save(output, format="PNG")
        return output.getvalue()
    except (OSError, ValueError):
        return data
