# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from functools import cache as memoize
from io import BytesIO
from typing import TYPE_CHECKING, Literal, NamedTuple, TypedDict

from PIL import Image, ImageEnhance, ImageOps

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

from .peak_pool_arrows import (
    CELL_GAP,
    CELL_WIDTH,
)
from .peak_pool_arrows import (
    pool_transition_arrows as _pool_transition_arrows,
)
from .peak_pool_arrows import (
    transition_overlay_uri as _transition_overlay_uri,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.peak import (
        PeakPetSnapshot,
        PeakPoolRenderSnapshot,
    )
    from ironsbot.services.seer.render_cache import RenderCache

    from . import HtmlTemplateRenderer

POOL_OVERHEAD = 18 * 2 + 1 * 2  # pool-section padding + border
CONTAINER_PADDING = 20 * 2
MAX_BASE_COLS = 10
PEAK_POOL_CACHE_VERSION = 12

logger = logging.getLogger(__name__)


class PetInPoolDict(TypedDict):
    id: int
    name: str
    head_img: str
    type_icon: str
    historical: bool


class PoolDict(TypedDict):
    label: str
    restriction: int | None
    current_count: int
    previous_count: int | None
    rows: int
    slots: list[PetInPoolDict | None]


class PoolImageUris(NamedTuple):
    heads: dict[str, str]
    historical_heads: dict[str, str]
    type_icons: dict[int, str]


GridSide = Literal["top", "bottom"]


@dataclass(frozen=True, slots=True)
class PoolPetPlacement:
    pet: PeakPetSnapshot
    historical: bool
    transition_id: int | None = None


@dataclass(frozen=True, slots=True)
class ReservedPlacement:
    placement: PoolPetPlacement
    side: GridSide
    column: int
    depth: int


@dataclass(frozen=True, slots=True)
class PoolSectionLayout:
    position: int | None
    rows: int
    slots: tuple[PoolPetPlacement | None, ...]


@dataclass(frozen=True, slots=True)
class PoolGridLayout:
    base_columns: int
    columns: int
    sections: tuple[PoolSectionLayout, ...]


@dataclass(frozen=True, slots=True)
class PoolGridDimensions:
    base_columns: int
    columns: int


@dataclass(frozen=True, slots=True)
class PoolTransitionLane:
    transition_index: int
    pet: PeakPetSnapshot
    previous_position: int | None
    current_position: int | None
    previous_index: int
    current_index: int
    lane: int


class PoolSlotCollisionError(RuntimeError):
    pass


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
                (pet.id, pet.name, pet.resource_id, pet.type_id) for pet in pool.pets
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
            snapshot.master,
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
    """Render the current peak pool with dimmed previous positions."""
    content_key = _peak_pool_cache_key(snapshot, pool_type)
    cached = cache.get("peak_pool", content_key)
    if cached is not None:
        return cached

    layout = _pool_grid_layout(snapshot)
    image_uris = await _pool_image_uris(
        images,
        layout,
    )
    pool_dicts = _pool_dicts(
        layout,
        image_uris,
        snapshot=snapshot,
        expert=snapshot.expert,
    )
    grid_width = layout.columns * CELL_WIDTH + (layout.columns - 1) * CELL_GAP
    stage_height, transition_arrows = _pool_transition_arrows(layout)
    transition_overlay = _transition_overlay_uri(
        grid_width + POOL_OVERHEAD,
        stage_height,
        transition_arrows,
    )
    max_width = grid_width + POOL_OVERHEAD + CONTAINER_PADDING

    result = await render_html(
        template_path=[PEAK_POOL_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates={
            "pools": pool_dicts,
            "bag_icons": _bag_icon_uris(),
            "pool_type": pool_type,
            "change_label": "大师池"
            if snapshot.master
            else ("专家池" if snapshot.expert else "竞技池"),
            "change_state": snapshot.change_state,
            "grid_width": grid_width,
            "grid_columns": layout.columns,
            "base_columns": layout.base_columns,
            "stage_height": stage_height,
            "transition_arrows": transition_arrows,
            "transition_overlay": transition_overlay,
            "transition_overlay_width": grid_width + POOL_OVERHEAD,
        },
        max_width=max_width + 20,
        allow_refit=False,
    )
    cache.put("peak_pool", content_key, result)
    return result


@memoize
def _bag_icon_uris() -> dict[str, str]:
    names = {
        "type_background": "newpetbagMainPanel_shuxingdi",
        "limit_background": "peakjihad_sports_pool_numbg",
        "ban_background": "peakjihad_sports_pool_banbg",
        "ban": "ban",
    }
    return {
        key: to_data_uri(
            (PEAK_POOL_TEMPLATE_PATH / "images" / f"{name}.png").read_bytes()
        )
        for key, name in names.items()
    }


def _pool_grid_layout(snapshot: PeakPoolRenderSnapshot) -> PoolGridLayout:
    positions: tuple[int | None, ...] = (
        (0, None) if snapshot.expert else (0, 2, 3, None)
    )
    if snapshot.master:
        costs = {pool.count for pool in snapshot.pools if pool.pets}
        costs.update(
            value
            for item in snapshot.transitions
            for value in (item.previous_limit, item.current_limit)
            if value is not None
        )
        positions = tuple(sorted(costs, reverse=True))
        if any(
            item.previous_limit is None or item.current_limit is None
            for item in snapshot.transitions
        ):
            positions = (*positions, None)
    current_pets = _current_pool_pets(snapshot, positions)
    transition_lanes = _transition_lanes(snapshot, positions)
    regular = _regular_pool_placements(
        snapshot,
        positions=positions,
        current_pets=current_pets,
        transition_lanes=transition_lanes,
    )
    dimensions = _pool_grid_dimensions(regular, transition_lanes)
    return _place_pool_pets(
        positions=positions,
        transition_lanes=transition_lanes,
        regular=regular,
        dimensions=dimensions,
    )


def _current_pool_pets(
    snapshot: PeakPoolRenderSnapshot,
    positions: tuple[int | None, ...],
) -> dict[int | None, list[PeakPetSnapshot]]:
    current_pets: dict[int | None, list[PeakPetSnapshot]] = {
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
                current_pets[position].append(pet)
                current_ids.add(pet.id)

    for transition in snapshot.transitions:
        if (
            transition.current_limit in current_pets
            and transition.pet.id not in current_ids
        ):
            current_pets[transition.current_limit].append(transition.pet)
            current_ids.add(transition.pet.id)
    return current_pets


def _transition_lanes(
    snapshot: PeakPoolRenderSnapshot,
    positions: tuple[int | None, ...],
) -> tuple[PoolTransitionLane, ...]:
    position_indexes = {position: index for index, position in enumerate(positions)}
    candidates: list[
        tuple[int, int, int, int, PeakPetSnapshot, int | None, int | None]
    ] = []
    for transition_index, transition in enumerate(snapshot.transitions):
        previous_index = position_indexes.get(transition.previous_limit)
        current_index = position_indexes.get(transition.current_limit)
        if (
            previous_index is None
            or current_index is None
            or previous_index == current_index
        ):
            continue
        candidates.append(
            (
                min(previous_index, current_index),
                max(previous_index, current_index),
                transition.pet.id,
                transition_index,
                transition.pet,
                transition.previous_limit,
                transition.current_limit,
            )
        )
    candidates.sort(key=lambda item: item[:4])

    lane_ends: list[int] = []
    result: list[PoolTransitionLane] = []
    for (
        interval_start,
        interval_end,
        _pet_id,
        transition_index,
        pet,
        previous_position,
        current_position,
    ) in candidates:
        lane = min(
            (
                candidate
                for candidate, previous_end in enumerate(lane_ends)
                if previous_end <= interval_start
            ),
            key=lambda candidate: (
                lane_ends[candidate] != interval_start,
                candidate,
            ),
            default=len(lane_ends),
        )
        if lane == len(lane_ends):
            lane_ends.append(interval_end)
        else:
            lane_ends[lane] = interval_end
        result.append(
            PoolTransitionLane(
                transition_index=transition_index,
                pet=pet,
                previous_position=previous_position,
                current_position=current_position,
                previous_index=position_indexes[previous_position],
                current_index=position_indexes[current_position],
                lane=lane,
            )
        )
    return tuple(result)


def _regular_pool_placements(
    snapshot: PeakPoolRenderSnapshot,
    *,
    positions: tuple[int | None, ...],
    current_pets: dict[int | None, list[PeakPetSnapshot]],
    transition_lanes: tuple[PoolTransitionLane, ...],
) -> dict[int | None, list[PoolPetPlacement]]:
    paired_transition_indexes = {
        transition.transition_index for transition in transition_lanes
    }
    paired_current = {
        (transition.current_position, transition.pet.id)
        for transition in transition_lanes
    }
    regular = {
        position: [
            PoolPetPlacement(pet, historical=False)
            for pet in current_pets[position]
            if (position, pet.id) not in paired_current
        ]
        for position in positions
    }
    for transition_index, transition in enumerate(snapshot.transitions):
        if (
            transition_index not in paired_transition_indexes
            and transition.previous_limit in regular
        ):
            regular[transition.previous_limit].append(
                PoolPetPlacement(transition.pet, historical=True)
            )
    return regular


def _pool_grid_dimensions(
    regular: dict[int | None, list[PoolPetPlacement]],
    transition_lanes: tuple[PoolTransitionLane, ...],
) -> PoolGridDimensions:
    max_items = max((len(items) for items in regular.values()), default=0)
    target_rows = max(
        1,
        _ceil_div(max_items, MAX_BASE_COLS),
        _max_transition_boundary_rows(transition_lanes),
    )
    base_columns = max(1, _ceil_div(max_items, target_rows))
    lane_count = max(
        (transition.lane + 1 for transition in transition_lanes),
        default=0,
    )
    return PoolGridDimensions(
        base_columns=base_columns,
        columns=base_columns + lane_count,
    )


def _max_transition_boundary_rows(
    transition_lanes: tuple[PoolTransitionLane, ...],
) -> int:
    endpoint_loads: dict[tuple[int | None, int], int] = {}
    for transition in transition_lanes:
        for position in (
            transition.previous_position,
            transition.current_position,
        ):
            key = (position, transition.lane)
            endpoint_loads[key] = endpoint_loads.get(key, 0) + 1
    return max(endpoint_loads.values(), default=0)


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def _place_pool_pets(
    *,
    positions: tuple[int | None, ...],
    transition_lanes: tuple[PoolTransitionLane, ...],
    regular: dict[int | None, list[PoolPetPlacement]],
    dimensions: PoolGridDimensions,
) -> PoolGridLayout:
    edge_loads: dict[tuple[int | None, GridSide], list[int]] = {
        (position, side): [0] * dimensions.columns
        for position in positions
        for side in ("top", "bottom")
    }
    reserved: dict[int | None, list[ReservedPlacement]] = {
        position: [] for position in positions
    }
    for transition in transition_lanes:
        previous = transition.previous_position
        current = transition.current_position
        previous_index = transition.previous_index
        current_index = transition.current_index
        previous_side: GridSide = "bottom" if previous_index < current_index else "top"
        current_side: GridSide = "top" if previous_index < current_index else "bottom"
        previous_loads = edge_loads[(previous, previous_side)]
        current_loads = edge_loads[(current, current_side)]
        column = dimensions.base_columns + transition.lane
        reserved[previous].append(
            ReservedPlacement(
                placement=PoolPetPlacement(
                    transition.pet,
                    historical=True,
                    transition_id=transition.transition_index,
                ),
                side=previous_side,
                column=column,
                depth=previous_loads[column],
            )
        )
        reserved[current].append(
            ReservedPlacement(
                placement=PoolPetPlacement(
                    transition.pet,
                    historical=False,
                    transition_id=transition.transition_index,
                ),
                side=current_side,
                column=column,
                depth=current_loads[column],
            )
        )
        previous_loads[column] += 1
        current_loads[column] += 1

    sections = [
        _place_pool_section(
            position,
            dimensions=dimensions,
            reserved=reserved[position],
            regular=regular[position],
            edge_loads=edge_loads,
        )
        for position in positions
    ]
    return PoolGridLayout(
        base_columns=dimensions.base_columns,
        columns=dimensions.columns,
        sections=tuple(sections),
    )


def _place_pool_section(
    position: int | None,
    *,
    dimensions: PoolGridDimensions,
    reserved: list[ReservedPlacement],
    regular: list[PoolPetPlacement],
    edge_loads: dict[tuple[int | None, GridSide], list[int]],
) -> PoolSectionLayout:
    item_count = len(reserved) + len(regular)
    if item_count == 0:
        return PoolSectionLayout(position=position, rows=0, slots=())

    base_item_count = len(regular) + sum(
        item.column < dimensions.base_columns for item in reserved
    )
    capacity_rows = _ceil_div(base_item_count, dimensions.base_columns)
    boundary_rows = max(
        (
            edge_loads[(position, "top")][column]
            + edge_loads[(position, "bottom")][column]
            for column in range(dimensions.columns)
        ),
        default=0,
    )
    rows = max(1, capacity_rows, boundary_rows)
    slots: list[PoolPetPlacement | None] = [None] * (rows * dimensions.columns)
    for item in reserved:
        row = item.depth if item.side == "top" else rows - 1 - item.depth
        slot_index = row * dimensions.columns + item.column
        if slots[slot_index] is not None:
            raise PoolSlotCollisionError(position, row, item.column)
        slots[slot_index] = item.placement

    empty_slots = (
        row * dimensions.columns + column
        for row in range(rows)
        for column in range(dimensions.base_columns)
        if slots[row * dimensions.columns + column] is None
    )
    for placement in regular:
        slots[next(empty_slots)] = placement
    return PoolSectionLayout(position=position, rows=rows, slots=tuple(slots))


async def _pool_image_uris(
    images: SeerImageSource,
    layout: PoolGridLayout,
) -> PoolImageUris:
    placements = [
        placement
        for section in layout.sections
        for placement in section.slots
        if placement is not None
    ]
    unique_rids = {str(placement.pet.resource_id) for placement in placements}
    unique_type_ids = {
        placement.pet.type_id for placement in placements if placement.pet.type_id > 0
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
    head_data = dict(zip(rid_list, head_results, strict=True))
    historical_rids = sorted(
        {
            str(placement.pet.resource_id)
            for placement in placements
            if placement.historical
            and head_data[str(placement.pet.resource_id)] is not None
        }
    )
    historical_results = await asyncio.gather(
        *(
            asyncio.to_thread(
                _dim_historical_head,
                head_data[rid],
                rid,
            )
            for rid in historical_rids
        )
    )
    normal_uris = {
        rid: "" if data is None else to_data_uri(data)
        for rid, data in head_data.items()
    }
    historical_uris = dict(normal_uris)
    historical_uris.update(
        {
            rid: to_data_uri(data)
            for rid, data in zip(historical_rids, historical_results, strict=True)
        }
    )
    return PoolImageUris(
        heads=normal_uris,
        historical_heads=historical_uris,
        type_icons={
            type_id: "" if data is None else to_data_uri(data)
            for type_id, data in zip(type_id_list, type_results, strict=True)
        },
    )


def _pool_dicts(
    layout: PoolGridLayout,
    image_uris: PoolImageUris,
    *,
    snapshot: PeakPoolRenderSnapshot,
    expert: bool,
) -> list[PoolDict]:
    positions = tuple(section.position for section in layout.sections)
    current_counts = {
        position: len(pets)
        for position, pets in _current_pool_pets(snapshot, positions).items()
    }
    previous_counts = dict(current_counts)
    if snapshot.change_state != "unavailable":
        for transition in snapshot.transitions:
            if transition.current_limit in previous_counts:
                previous_counts[transition.current_limit] -= 1
            if transition.previous_limit in previous_counts:
                previous_counts[transition.previous_limit] += 1

    return [
        {
            "restriction": None if snapshot.master else section.position,
            "label": (
                ("未列入" if section.position is None else f"{section.position} 点")
                if snapshot.master
                else _pool_position_label(section.position, expert=expert)
            ),
            "current_count": current_counts[section.position],
            "previous_count": (
                None
                if snapshot.change_state == "unavailable"
                else previous_counts[section.position]
            ),
            "rows": section.rows,
            "slots": [
                None if placement is None else _pool_pet_dict(placement, image_uris)
                for placement in section.slots
            ],
        }
        for section in layout.sections
    ]


def _pool_pet_dict(
    placement: PoolPetPlacement,
    image_uris: PoolImageUris,
) -> PetInPoolDict:
    pet = placement.pet
    return {
        "id": pet.id,
        "name": pet.name,
        "head_img": (
            image_uris.historical_heads[str(pet.resource_id)]
            if placement.historical
            else image_uris.heads[str(pet.resource_id)]
        ),
        "type_icon": image_uris.type_icons.get(pet.type_id, ""),
        "historical": placement.historical,
    }


def _dim_historical_head(data: bytes | None, resource_id: str) -> bytes:
    if data is None:
        return b""
    try:
        # htmlkit's native renderer ignores CSS filters, so alter source pixels.
        with Image.open(BytesIO(data)) as source:
            rgba = source.convert("RGBA")
        alpha = rgba.getchannel("A")
        rgb = rgba.convert("RGB")
        grayscale = ImageOps.grayscale(rgb).convert("RGB")
        dimmed = ImageEnhance.Brightness(Image.blend(rgb, grayscale, 0.75)).enhance(0.5)
        dimmed.putalpha(alpha)
        output = BytesIO()
        dimmed.save(output, format="PNG")
        return output.getvalue()
    except (OSError, ValueError):
        logger.warning(
            "peak pool historical head transform failed: resource_id=%s",
            resource_id,
            exc_info=True,
        )
        return data


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
