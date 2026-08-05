# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose peak pet-rank snapshots, assets, cache, and the HTML render port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rendering.cache_key import render_document_cache_key
from ironsbot.services.seer.rendering.peak_pet_rank import (
    present_peak_pet_rank,
    render_peak_pet_rank_document,
)

from .pet_image_assets import load_pet_image_assets

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
    assets = await load_pet_image_assets(
        images,
        resource_ids=(pet.resource_id for pet in input_.pets),
        type_ids=(pet.type_id for pet in input_.pets),
    )
    document = present_peak_pet_rank(input_, assets)
    content_key = render_document_cache_key(document)
    if cached := cache.get(_CACHE_CATEGORY, content_key):
        return cached
    rendered = await render_peak_pet_rank_document(render_html, document)
    cache.put(_CACHE_CATEGORY, content_key, rendered)
    return rendered
