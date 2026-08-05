# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose peak-vote snapshots, assets, cache, and the HTML render port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rendering.peak_pool_vote import (
    peak_pool_vote_cache_key,
    present_peak_pool_vote,
    render_peak_pool_vote_document,
)

from .pet_image_assets import load_pet_image_assets

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.peak import PeakVotePoolInput
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer

_CACHE_CATEGORY = "peak_pool_vote"


async def render_peak_pool_vote(
    cache: RenderCache,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    pools: Sequence[PeakVotePoolInput],
    generated_at: str,
) -> bytes:
    """Render one vote result after cache lookup and shared asset retrieval."""
    content_key = peak_pool_vote_cache_key(pools, generated_at)
    if cached := cache.get(_CACHE_CATEGORY, content_key):
        return cached
    assets = await load_pet_image_assets(
        images,
        resource_ids=(pet.resource_id for pool in pools for pet in pool.pets),
        type_ids=(pet.type_id for pool in pools for pet in pool.pets),
    )
    document = present_peak_pool_vote(pools, generated_at, assets)
    rendered = await render_peak_pool_vote_document(render_html, document)
    cache.put(_CACHE_CATEGORY, content_key, rendered)
    return rendered
