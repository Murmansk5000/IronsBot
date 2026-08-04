# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose peak-pool snapshots, assets, cache, and the HTML render port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rendering.peak_pool import (
    peak_pool_cache_key,
    present_peak_pool,
    render_peak_pool_document,
)

from .peak_render_assets import load_peak_render_assets

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
    content_key = peak_pool_cache_key(pools, pool_type)
    if cached := cache.get(_CACHE_CATEGORY, content_key):
        return cached
    assets = await load_peak_render_assets(
        images,
        (pet for pool in pools for pet in pool.pets),
    )
    document = present_peak_pool(pools, pool_type, assets)
    rendered = await render_peak_pool_document(render_html, document)
    cache.put(_CACHE_CATEGORY, content_key, rendered)
    return rendered
