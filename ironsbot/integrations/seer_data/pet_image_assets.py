# SPDX-License-Identifier: GPL-3.0-or-later
"""Load reusable pet-head and type-icon render assets through the image port."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ironsbot.services.seer.images import to_data_uri
from ironsbot.services.seer.rendering.pet_image_assets import PetImageAssets

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.services.seer.images import SeerImageSource


async def load_pet_image_assets(
    images: SeerImageSource,
    *,
    resource_ids: Iterable[int],
    type_ids: Iterable[int],
) -> PetImageAssets:
    """Fetch distinct usable pet-head and type-icon assets once per render."""
    distinct_resource_ids = tuple(sorted({id_ for id_ in resource_ids if id_ > 0}))
    distinct_type_ids = tuple(sorted({id_ for id_ in type_ids if id_ > 0}))
    values = await asyncio.gather(
        *(
            images.fetch("pet_head", str(resource_id), fallback=False)
            for resource_id in distinct_resource_ids
        ),
        *(
            images.fetch("element_type", str(type_id), fallback=False)
            for type_id in distinct_type_ids
        ),
    )
    head_values = values[: len(distinct_resource_ids)]
    type_values = values[len(distinct_resource_ids) :]
    return PetImageAssets(
        pet_heads=tuple(
            (resource_id, to_data_uri(value))
            for resource_id, value in zip(
                distinct_resource_ids,
                head_values,
                strict=True,
            )
        ),
        type_icons=tuple(
            (type_id, to_data_uri(value))
            for type_id, value in zip(
                distinct_type_ids,
                type_values,
                strict=True,
            )
        ),
    )
