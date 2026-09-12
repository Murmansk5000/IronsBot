# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose peak-vote snapshots, assets, cache, and the HTML render port."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.rendering.peak_pool_vote import (
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
    pools = tuple(pools)
    request_key = render_request_cache_key(
        _CACHE_CATEGORY,
        (generated_at, pools),
    )
    cache_entry = cache.entry(_CACHE_CATEGORY, request_key)
    if cached := cache_entry.get():
        return cached
    assets = await load_pet_image_assets(
        images,
        resource_ids=(pet.resource_id for pool in pools for pet in pool.pets),
        type_ids=(pet.type_id for pool in pools for pet in pool.pets),
    )
    document = present_peak_pool_vote(pools, generated_at, assets)
    rendered = await render_peak_pool_vote_document(render_html, document)
    cache_entry.put(rendered)
    return rendered
