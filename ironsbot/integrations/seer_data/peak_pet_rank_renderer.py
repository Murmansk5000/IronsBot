# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose peak pet-rank snapshots, assets, cache, and the HTML render port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rendering.peak_pet_rank import (
    peak_pet_rank_cache_key,
    present_peak_pet_rank,
    render_peak_pet_rank_document,
)

from .peak_render_assets import load_peak_render_assets

if TYPE_CHECKING:
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.peak import PeakPetRankRenderInput
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer

_CACHE_CATEGORY = "peak_pet_rank"


async def render_peak_pet_rank(
    cache: RenderCache,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    input_: PeakPetRankRenderInput,
) -> bytes:
    """Render one pet rank after cache lookup and shared asset retrieval."""
    content_key = peak_pet_rank_cache_key(input_)
    if cached := cache.get(_CACHE_CATEGORY, content_key):
        return cached
    assets = await load_peak_render_assets(images, input_.pets)
    document = present_peak_pet_rank(input_, assets)
    rendered = await render_peak_pet_rank_document(render_html, document)
    cache.put(_CACHE_CATEGORY, content_key, rendered)
    return rendered
