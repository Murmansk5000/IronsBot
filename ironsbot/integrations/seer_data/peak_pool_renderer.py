# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose peak-pool snapshots, assets, cache, and the HTML render port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.rendering.peak_pool import (
    present_peak_pool,
    render_peak_pool_document,
)

from .pet_image_assets import load_pet_image_assets

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.peak import PeakPoolSnapshot
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer

_CACHE_CATEGORY = "peak_pool"


async def render_peak_pool(
    cache: RenderCache,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    pools: Sequence[PeakPoolSnapshot],
    pool_type: str,
) -> bytes:
    """Render one pool after cache lookup and shared asset retrieval."""
    pools = tuple(pools)
    request_key = render_request_cache_key(_CACHE_CATEGORY, (pool_type, pools))
    if cached := cache.get(_CACHE_CATEGORY, request_key):
        return cached
    assets = await load_pet_image_assets(
        images,
        resource_ids=(pet.resource_id for pool in pools for pet in pool.pets),
        type_ids=(pet.type_id for pool in pools for pet in pool.pets),
    )
    document = present_peak_pool(pools, pool_type, assets)
    rendered = await render_peak_pool_document(render_html, document)
    cache.put(_CACHE_CATEGORY, request_key, rendered)
    return rendered
