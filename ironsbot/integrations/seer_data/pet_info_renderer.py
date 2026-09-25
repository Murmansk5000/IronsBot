# SPDX-License-Identifier: MIT
"""Compose detached pet snapshots, assets, and the HTML rendering port."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ironsbot.services.seer.image_failure_notice import report_render_asset_failures
from ironsbot.services.seer.images import ImageSourceError, placeholder_image
from ironsbot.services.seer.pet_info_views import PetInfoAssets
from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    PET_INFO_IMAGES_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.cache_key import render_request_cache_key
from ironsbot.services.seer.rendering.pet_info_presentation import present_pet_info
from ironsbot.services.seer.rendering.pet_info_renderer import render_pet_info_document

from .pet_info_repository import load_pet_info_snapshot

if TYPE_CHECKING:
    from ironsbot.core.outbound import ExecutionIdentity
    from ironsbot.services.seer.data import SeerDataReader
    from ironsbot.services.seer.images import (
        ImageFailureReporter,
        ImageKind,
        SeerImageSource,
    )
    from ironsbot.services.seer.pet_info_views import (
        PetInfoSnapshot,
        PetItemSnapshot,
    )
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer

# Keep this aligned with the published manifest scope. The renderer source
# fingerprint already invalidates previous layouts without turning the cache
# category into a versioned implementation detail.
_PET_INFO_CACHE_CATEGORY = "pet_info"
PET_INFO_RENDERER_SOURCE_PATH = Path(__file__).resolve()
logger = logging.getLogger(__name__)


class PetInfoNotFoundError(LookupError):
    """The requested pet disappeared between selection and render preparation."""

    def __init__(self, pet_id: int) -> None:
        super().__init__(f"pet {pet_id} no longer exists")


async def render_published_pet_info(  # noqa: PLR0913 - explicit integration ports
    cache: RenderCache,
    data: SeerDataReader,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    pet_id: int,
    *,
    image_failure_reporter: ImageFailureReporter | None = None,
    execution_identity: ExecutionIdentity | None = None,
) -> bytes:
    """Render one pet after completely detaching its data from SQLite."""
    request_key = render_request_cache_key(_PET_INFO_CACHE_CATEGORY, pet_id)
    cache_entry = cache.entry(_PET_INFO_CACHE_CATEGORY, request_key)
    if cached := cache_entry.get():
        return cached
    with data.query(
        lambda session: load_pet_info_snapshot(session, pet_id)
    ) as snapshot:
        if snapshot is None:
            raise PetInfoNotFoundError(pet_id)
    assets, complete = await _load_assets(
        images,
        snapshot,
        image_failure_reporter,
        execution_identity,
    )
    document = present_pet_info(snapshot, assets)
    rendered = await render_pet_info_document(
        render_html,
        [CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        document,
    )
    if complete:
        cache_entry.put(rendered)
    return rendered


async def _load_assets(
    images: SeerImageSource,
    snapshot: PetInfoSnapshot,
    image_failure_reporter: ImageFailureReporter | None = None,
    execution_identity: ExecutionIdentity | None = None,
) -> tuple[PetInfoAssets, bool]:
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
    soulmark_icons = snapshot.display.soulmark_icon_by_id
    soulmark_icon_ids = tuple(
        sorted({icon.icon_id for icon in soulmark_icons.values() if icon.icon_id > 0})
    )
    requested = await asyncio.gather(
        _load_render_asset(images, "pet_head", str(snapshot.pet.resource_id)),
        _load_render_asset(images, "pet_body", str(snapshot.pet.resource_id)),
        *(
            _load_render_asset(images, "element_type", str(type_id))
            for type_id in type_ids
        ),
        _load_render_asset(images, "element_type", "prop"),
        *(
            _load_render_asset(images, "mintmark", str(mintmark_id))
            for mintmark_id in mintmark_ids
        ),
        *(_load_render_asset(images, "item", str(item_id)) for item_id in item_ids),
        *(
            _load_render_asset(images, "sign_buff", str(status_id))
            for status_id in status_ids
        ),
        *(
            _load_soulmark_icon_asset(images, icon_id)
            for icon_id in soulmark_icon_ids
        ),
    )
    type_offset = 2
    prop_offset = type_offset + len(type_ids)
    mintmark_offset = prop_offset + 1
    item_offset = mintmark_offset + len(mintmark_ids)
    effect_offset = item_offset + len(item_ids)
    soulmark_offset = effect_offset + len(status_ids)
    unity_soulmark_icons = {
        icon_id: requested[soulmark_offset + index]
        for index, icon_id in enumerate(soulmark_icon_ids)
    }
    display_soulmark_icons = tuple(
        (
            soulmark_id,
            result.data if result.error is None else icon.png or result.data,
        )
        for soulmark_id, icon in soulmark_icons.items()
        if (result := unity_soulmark_icons.get(icon.icon_id)) is not None
    )
    assets = PetInfoAssets(
        gender_icon=_load_gender_icon(snapshot.pet.gender_id),
        pet_head=requested[0].data,
        pet_body=requested[1].data,
        type_icons=(
            *(
                (type_id, requested[type_offset + index].data)
                for index, type_id in enumerate(type_ids)
            ),
            ("prop", requested[prop_offset].data),
        ),
        mintmark_icons=tuple(
            (mintmark_id, requested[mintmark_offset + index].data)
            for index, mintmark_id in enumerate(mintmark_ids)
        ),
        item_icons=tuple(
            (item_id, requested[item_offset + index].data)
            for index, item_id in enumerate(item_ids)
        ),
        special_effect_icons=tuple(
            (status_id, requested[effect_offset + index].data)
            for index, status_id in enumerate(status_ids)
        ),
        soulmark_icons=display_soulmark_icons,
    )
    failures = tuple(result for result in requested if result.error is not None)
    flash_icon_ids = {
        icon_id
        for icon_id in soulmark_icon_ids
        if all(
            icon.png is not None
            for icon in soulmark_icons.values()
            if icon.icon_id == icon_id
        )
    }
    reportable_failures = tuple(
        result
        for result in failures
        if result.kind != "soulmark_icon" or int(result.key) not in flash_icon_ids
    )
    if reportable_failures and image_failure_reporter is not None:
        await report_render_asset_failures(
            image_failure_reporter,
            tuple(
                (item.kind, item.key, item.error)
                for item in reportable_failures
                if item.error is not None
            ),
            execution_identity,
        )
    return assets, not failures


@dataclass(frozen=True, slots=True)
class _LoadedRenderAsset:
    kind: ImageKind
    key: str
    data: bytes
    error: ImageSourceError | None = None


async def _load_render_asset(
    images: SeerImageSource,
    kind: ImageKind,
    key: str,
) -> _LoadedRenderAsset:
    try:
        data = await images.fetch(kind, key, fallback=False)
    except ImageSourceError as error:
        logger.warning(
            "pet info asset replaced with placeholder: kind=%s key=%s error_type=%s",
            kind,
            key,
            type(error).__name__,
        )
        return _LoadedRenderAsset(kind, key, placeholder_image(kind), error)
    return _LoadedRenderAsset(kind, key, data)


async def _load_soulmark_icon_asset(
    images: SeerImageSource, icon_id: int
) -> _LoadedRenderAsset:
    key = str(icon_id)
    try:
        data = await images.fetch("soulmark_icon", key, fallback=False)
    except ImageSourceError as error:
        logger.warning(
            "Unity soulmark icon unavailable; trying Flash fallback: "
            "icon_id=%s error_type=%s",
            icon_id,
            type(error).__name__,
        )
        return _LoadedRenderAsset(
            "soulmark_icon", key, placeholder_image("soulmark_icon"), error
        )
    return _LoadedRenderAsset("soulmark_icon", key, data)


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
