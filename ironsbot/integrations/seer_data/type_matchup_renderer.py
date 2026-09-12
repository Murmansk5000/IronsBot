# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose type-matchup data, published assets, and the HTML render port."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ironsbot.services.seer.images import to_data_uri
from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.rendering.type_matchup import (
    TypeMatchupAssets,
    present_type_matchup,
    render_type_matchup_document,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer
    from ironsbot.services.seer.type_calc import TypeMatchup

_CACHE_CATEGORY = "type_matchup"


async def render_type_matchup(
    cache: RenderCache,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    matchup: TypeMatchup,
) -> bytes:
    """Render one matchup after cache lookup and shared asset retrieval."""
    request_key = render_request_cache_key(_CACHE_CATEGORY, matchup.cache_key)
    if cached := cache.get(_CACHE_CATEGORY, request_key):
        return cached
    assets = await _load_assets(images, matchup)
    document = present_type_matchup(matchup, assets)
    rendered = await render_type_matchup_document(render_html, document)
    cache.put(_CACHE_CATEGORY, request_key, rendered)
    return rendered


async def _load_assets(
    images: SeerImageSource,
    matchup: TypeMatchup,
) -> TypeMatchupAssets:
    target = matchup.target
    table_icon_ids = {
        int(combination.id)
        for combination, _multiplier in (*matchup.attack_table, *matchup.defense_table)
    }
    if target.id < 0:
        target_icon_ids = (target.primary_id, target.secondary_id)
    else:
        target_icon_ids = (target.id,)
    icon_ids = tuple(sorted(table_icon_ids | {id_ for id_ in target_icon_ids if id_}))
    values = await asyncio.gather(
        *(
            images.fetch("element_type", str(icon_id), fallback=False)
            for icon_id in icon_ids
        )
    )
    icon_by_id = {
        icon_id: to_data_uri(value)
        for icon_id, value in zip(icon_ids, values, strict=True)
    }
    return TypeMatchupAssets(
        icons=tuple(icon_by_id.items()),
        target_icon=icon_by_id[target_icon_ids[0]],
        target_icon_secondary=(
            None
            if len(target_icon_ids) == 1 or target_icon_ids[1] is None
            else icon_by_id[target_icon_ids[1]]
        ),
    )
