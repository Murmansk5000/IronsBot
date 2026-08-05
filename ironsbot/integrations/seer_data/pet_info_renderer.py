# SPDX-License-Identifier: MIT
"""Compose detached pet snapshots, assets, and the HTML rendering port."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from ironsbot.services.seer.images import fetch_optional_image
from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    PET_INFO_IMAGES_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.cache_key import render_document_cache_key
from ironsbot.services.seer.rendering.pet_info_models import PetInfoAssets
from ironsbot.services.seer.rendering.pet_info_presentation import present_pet_info
from ironsbot.services.seer.rendering.pet_info_renderer import render_pet_info_document

from .pet_info_repository import load_pet_info_snapshot

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer
    from ironsbot.services.seer.rendering.pet_info_models import (
        PetInfoSnapshot,
        PetItemSnapshot,
    )

_PET_INFO_CACHE_CATEGORY = "pet_info_v18"
PET_INFO_RENDERER_SOURCE_PATH = Path(__file__).resolve()


class PetInfoNotFoundError(LookupError):
    """The requested pet disappeared between selection and render preparation."""

    def __init__(self, pet_id: int) -> None:
        super().__init__(f"pet {pet_id} no longer exists")


async def render_published_pet_info(
    cache: RenderCache,
    data: SeerDataAccess,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    pet_id: int,
) -> bytes:
    """Render one pet after completely detaching its data from SQLite."""
    with data.query(
        lambda session: load_pet_info_snapshot(session, pet_id)
    ) as snapshot:
        if snapshot is None:
            raise PetInfoNotFoundError(pet_id)
    assets = await _load_assets(images, snapshot)
    document = present_pet_info(snapshot, assets)
    content_key = render_document_cache_key(document)
    if cached := cache.get(_PET_INFO_CACHE_CATEGORY, content_key):
        return cached
    rendered = await render_pet_info_document(
        render_html,
        [CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        document,
    )
    cache.put(_PET_INFO_CACHE_CATEGORY, content_key, rendered)
    return rendered


async def _load_assets(
    images: SeerImageSource,
    snapshot: PetInfoSnapshot,
) -> PetInfoAssets:
    type_ids = tuple(
        sorted({snapshot.pet.type_id, *(skill.type_id for skill in snapshot.skills)})
    )
    mintmark_ids = tuple(mintmark.id for mintmark in snapshot.skill_mintmarks)
    item_ids = _item_ids(snapshot)
    status_ids = tuple(
        sorted(
            {
                effect.status_id
                for effect in snapshot.display.special_effects
                if effect.status_id is not None
            }
        )
    )
    mandatory = await asyncio.gather(
        images.fetch("pet_head", str(snapshot.pet.resource_id)),
        images.fetch("pet_body", str(snapshot.pet.resource_id)),
        *(images.fetch("element_type", str(type_id)) for type_id in type_ids),
        images.fetch("element_type", "prop"),
        *(images.fetch("mintmark", str(mintmark_id)) for mintmark_id in mintmark_ids),
    )
    optional = await asyncio.gather(
        *(fetch_optional_image(images, "item", str(item_id)) for item_id in item_ids),
        *(
            fetch_optional_image(images, "sign_buff", str(status_id))
            for status_id in status_ids
        ),
    )
    type_offset = 2
    prop_offset = type_offset + len(type_ids)
    mintmark_offset = prop_offset + 1
    item_results = optional[: len(item_ids)]
    effect_results = optional[len(item_ids) :]
    return PetInfoAssets(
        gender_icon=_load_gender_icon(snapshot.pet.gender_id),
        pet_head=mandatory[0],
        pet_body=mandatory[1],
        type_icons=(
            *(
                (type_id, mandatory[type_offset + index])
                for index, type_id in enumerate(type_ids)
            ),
            ("prop", mandatory[prop_offset]),
        ),
        mintmark_icons=tuple(
            (mintmark_id, mandatory[mintmark_offset + index])
            for index, mintmark_id in enumerate(mintmark_ids)
        ),
        item_icons=tuple(
            (item_id, result.data)
            for item_id, result in zip(item_ids, item_results, strict=True)
            if result.data is not None
        ),
        special_effect_icons=tuple(
            (status_id, result.data)
            for status_id, result in zip(status_ids, effect_results, strict=True)
            if result.data is not None
        ),
    )


def _item_ids(snapshot: PetInfoSnapshot) -> tuple[int, ...]:
    item_ids = {item.id for item in snapshot.activation_items}
    for item in snapshot.activation_items:
        item_ids.update(price.currency_item_id for price in item.prices)
    if snapshot.partner is not None:
        _collect_item_ids(item_ids, snapshot.partner.cost_item)
        if snapshot.partner.skill and snapshot.partner.skill.activation_item:
            _collect_item_ids(item_ids, snapshot.partner.skill.activation_item)
    return tuple(sorted(item_ids))


def _collect_item_ids(item_ids: set[int], item: PetItemSnapshot) -> None:
    # Both activation and partner requirements are PetItemSnapshot values.
    prices = item.prices
    item_ids.add(int(item.id))
    item_ids.update(int(price.currency_item_id) for price in prices)


def _load_gender_icon(gender_id: int) -> bytes:
    path = PET_INFO_IMAGES_PATH / f"{gender_id}.png"
    if not path.exists():
        path = PET_INFO_IMAGES_PATH / "0.png"
    return path.read_bytes()
