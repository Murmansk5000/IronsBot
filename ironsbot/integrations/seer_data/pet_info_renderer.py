# SPDX-License-Identifier: MIT
"""Adapt published SeerAPI display facts to the pet information renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import object_session

from ironsbot.integrations.seer_data.pet_display_data import (
    load_pet_derived_display_data,
)
from ironsbot.services.seer.rendering.custom_pet_info import (
    render_custom_pet_info,
)

if TYPE_CHECKING:
    from seerapi_models import PetORM

    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


async def render_published_pet_info(
    cache: RenderCache,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    pet: PetORM,
) -> bytes:
    """Load build-time facts at the integration edge before rendering."""
    session = object_session(pet)
    if session is None:
        raise RuntimeError
    derived_display = load_pet_derived_display_data(
        session,
        pet_id=int(pet.id),
        soulmark_ids=(int(soulmark.id) for soulmark in pet.soulmark),
    )
    return await render_custom_pet_info(
        cache,
        images,
        render_html,
        pet,
        derived_display,
    )
