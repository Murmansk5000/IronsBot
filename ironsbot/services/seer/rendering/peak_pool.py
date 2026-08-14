# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING, TypedDict

from ironsbot.services.seer.images import (
    ImageKind,
    ImageSourceError,
    SeerImageSource,
    to_data_uri,
)
from ironsbot.services.seer.render_paths import (
    PEAK_POOL_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.peak import (
        PeakPetSnapshot,
        PeakPoolRenderSnapshot,
    )
    from ironsbot.services.seer.render_cache import RenderCache

    from . import HtmlTemplateRenderer

CELL_WIDTH = 100 + 2 * 2  # pet-cell width + border
CELL_GAP = 10
POOL_OVERHEAD = 18 * 2 + 1 * 2  # pool-section padding + border
CONTAINER_PADDING = 20 * 2
MAX_COLS = 10
PEAK_POOL_CACHE_VERSION = 2

logger = logging.getLogger(__name__)


class PetInPoolDict(TypedDict):
    id: int
    name: str
    head_img: str
    type_icon: str
    historical: bool


class PoolDict(TypedDict):
    label: str
    current_count: int
    historical_count: int
    pets: list[PetInPoolDict]


def _peak_pool_cache_key(
    snapshot: PeakPoolRenderSnapshot,
    pool_type: str,
) -> str:
    pools = tuple(
        (
            pool.id,
            pool.count,
            pool.start_time.isoformat(),
            pool.end_time.isoformat(),
            tuple(
                (pet.id, pet.name, pet.resource_id, pet.type_id)
                for pet in pool.pets
            ),
        )
        for pool in snapshot.pools
    )
    transitions = tuple(
        (
            item.pet.id,
            item.pet.name,
            item.pet.resource_id,
            item.pet.type_id,
            item.previous_limit,
            item.current_limit,
        )
        for item in snapshot.transitions
    )
    raw = repr(
        (
            PEAK_POOL_CACHE_VERSION,
            pool_type,
            snapshot.expert,
            snapshot.change_state,
            snapshot.content_version,
            pools,
            transitions,
        )
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


async def render_peak_pool(
    cache: RenderCache,
    images: SeerImageSource,
    render_html: HtmlTemplateRenderer,
    snapshot: PeakPoolRenderSnapshot,
    pool_type: str,
) -> bytes:
    """Render the current peak pool with translucent previous positions."""
    content_key = _peak_pool_cache_key(snapshot, pool_type)
    cached = cache.get("peak_pool", content_key)
    if cached is not None:
        return cached

    positions, section_pets = _positioned_pets(snapshot)
    head_data_uris, type_data_uris = await _pool_image_uris(
        images,
        section_pets,
    )
    pool_dicts = _pool_dicts(
        positions,
        section_pets,
        head_data_uris,
        type_data_uris,
        expert=snapshot.expert,
    )

    max_pets = max((len(pool["pets"]) for pool in pool_dicts), default=1)
    cols = max(1, min(max_pets, MAX_COLS))
    grid_width = cols * CELL_WIDTH + (cols - 1) * CELL_GAP
    max_width = grid_width + POOL_OVERHEAD + CONTAINER_PADDING

    result = await render_html(
        template_path=[PEAK_POOL_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates={
            "pools": pool_dicts,
            "pool_type": pool_type,
            "change_label": "专家池" if snapshot.expert else "竞技池",
            "change_state": snapshot.change_state,
        },
        max_width=max_width + 20,
        allow_refit=False,
    )
    cache.put("peak_pool", content_key, result)
    return result


def _positioned_pets(
    snapshot: PeakPoolRenderSnapshot,
) -> tuple[
    tuple[int | None, ...],
    dict[int | None, list[tuple[PeakPetSnapshot, bool]]],
]:
    positions: tuple[int | None, ...] = (
        (0, None) if snapshot.expert else (0, 2, 3, None)
    )
    section_pets: dict[int | None, list[tuple[PeakPetSnapshot, bool]]] = {
        position: [] for position in positions
    }
    current_ids: set[int] = set()
    for position in positions:
        if position is None:
            continue
        for pool in snapshot.pools:
            pool_position = 0 if snapshot.expert else pool.count
            if pool_position != position:
                continue
            for pet in pool.pets:
                if pet.id in current_ids:
                    continue
                section_pets[position].append((pet, False))
                current_ids.add(pet.id)

    for transition in snapshot.transitions:
        if transition.previous_limit in section_pets:
            section_pets[transition.previous_limit].append(
                (transition.pet, True)
            )
        if (
            transition.current_limit in section_pets
            and transition.pet.id not in current_ids
        ):
            section_pets[transition.current_limit].append(
                (transition.pet, False)
            )
            current_ids.add(transition.pet.id)
    return positions, section_pets


async def _pool_image_uris(
    images: SeerImageSource,
    section_pets: dict[int | None, list[tuple[PeakPetSnapshot, bool]]],
) -> tuple[dict[str, str], dict[int, str]]:
    unique_rids = {
        str(pet.resource_id)
        for pets in section_pets.values()
        for pet, _historical in pets
    }
    unique_type_ids = {
        pet.type_id
        for pets in section_pets.values()
        for pet, _historical in pets
        if pet.type_id > 0
    }
    rid_list = sorted(unique_rids)
    type_id_list = sorted(unique_type_ids)
    results = await asyncio.gather(
        *(_optional_image(images, "pet_head", rid) for rid in rid_list),
        *(
            _optional_image(images, "element_type", str(type_id))
            for type_id in type_id_list
        ),
    )
    head_results = results[: len(rid_list)]
    type_results = results[len(rid_list) :]
    return (
        {
            rid: "" if data is None else to_data_uri(data)
            for rid, data in zip(rid_list, head_results, strict=True)
        },
        {
            type_id: "" if data is None else to_data_uri(data)
            for type_id, data in zip(type_id_list, type_results, strict=True)
        },
    )


def _pool_dicts(
    positions: tuple[int | None, ...],
    section_pets: dict[int | None, list[tuple[PeakPetSnapshot, bool]]],
    head_data_uris: dict[str, str],
    type_data_uris: dict[int, str],
    *,
    expert: bool,
) -> list[PoolDict]:
    result: list[PoolDict] = []
    for position in positions:
        pets = section_pets[position]
        result.append(
            {
                "label": _pool_position_label(position, expert=expert),
                "current_count": sum(not historical for _, historical in pets),
                "historical_count": sum(historical for _, historical in pets),
                "pets": [
                    {
                        "id": pet.id,
                        "name": pet.name,
                        "head_img": head_data_uris[str(pet.resource_id)],
                        "type_icon": type_data_uris.get(pet.type_id, ""),
                        "historical": historical,
                    }
                    for pet, historical in pets
                ],
            }
        )
    return result


async def _optional_image(
    images: SeerImageSource,
    kind: ImageKind,
    key: str,
) -> bytes | None:
    try:
        return await images.fetch(kind, key, fallback=False)
    except (ImageSourceError, RuntimeError, TypeError, ValueError):
        logger.warning("peak pool image unavailable: kind=%s key=%s", kind, key)
        return None


def _pool_position_label(value: int | None, *, expert: bool) -> str:
    if value is None:
        return "不限"
    if expert:
        return "禁用"
    return f"限{value}"
