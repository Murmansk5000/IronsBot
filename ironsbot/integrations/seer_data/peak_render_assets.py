# SPDX-License-Identifier: GPL-3.0-or-later
"""Load shared peak-render image assets through the Seer image port."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ironsbot.services.seer.images import to_data_uri
from ironsbot.services.seer.rendering.peak_assets import PeakRenderAssets

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.peak import PeakPetSnapshot


async def load_peak_render_assets(
    images: SeerImageSource,
    pets: Iterable[PeakPetSnapshot],
) -> PeakRenderAssets:
    """Fetch the distinct head and type images required by peak documents."""
    snapshot = tuple(pets)
    resource_ids = tuple(sorted({pet.resource_id for pet in snapshot}))
    type_ids = tuple(sorted({pet.type_id for pet in snapshot}))
    results = await asyncio.gather(
        *(images.fetch("pet_head", str(resource_id)) for resource_id in resource_ids),
        *(images.fetch("element_type", str(type_id)) for type_id in type_ids),
    )
    head_values = results[: len(resource_ids)]
    type_values = results[len(resource_ids) :]
    return PeakRenderAssets(
        pet_heads=tuple(
            (resource_id, to_data_uri(value))
            for resource_id, value in zip(resource_ids, head_values, strict=True)
        ),
        type_icons=tuple(
            (type_id, to_data_uri(value))
            for type_id, value in zip(type_ids, type_values, strict=True)
        ),
    )
