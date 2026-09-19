# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation and HTML rendering for peak pools and weekly movement."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from ironsbot.services.seer.render_paths import (
    PEAK_POOL_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)

from .peak_pool_arrows import (
    CELL_GAP,
    CELL_WIDTH,
    PoolTransitionArrow,
    pool_transition_arrows,
    transition_overlay_uri,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.seer.peak import (
        PeakPetSnapshot,
        PeakPoolRenderSnapshot,
    )

    from . import HtmlTemplateRenderer

POOL_OVERHEAD = 38
CONTAINER_PADDING = 40
MAX_BASE_COLUMNS = 10


@dataclass(frozen=True, slots=True)
class PeakPoolImageAssets:
    heads: tuple[tuple[int, str], ...]
    historical_heads: tuple[tuple[int, str], ...]
    type_icons: tuple[tuple[int, str], ...]

    @property
    def head_by_resource_id(self) -> Mapping[int, str]:
        return MappingProxyType(dict(self.heads))

    @property
    def historical_head_by_resource_id(self) -> Mapping[int, str]:
        return MappingProxyType(dict(self.historical_heads))

    @property
    def type_icon_by_id(self) -> Mapping[int, str]:
        return MappingProxyType(dict(self.type_icons))


@dataclass(frozen=True, slots=True)
class PeakPoolPetDocument:
    id: int
    name: str
    head_img: str
    type_icon: str
    historical: bool


@dataclass(frozen=True, slots=True)
class PeakPoolDocument:
    label: str
    current_count: int
    previous_count: int | None
    rows: int
    slots: tuple[PeakPoolPetDocument | None, ...]


@dataclass(frozen=True, slots=True)
class PeakPoolRenderDocument:
    pools: tuple[PeakPoolDocument, ...]
    pool_type: str
    change_label: str
    change_state: str
    grid_width: int
    grid_columns: int
    base_columns: int
    stage_height: int
    transition_arrows: tuple[PoolTransitionArrow, ...]
    transition_overlay: str
    transition_overlay_width: int
    max_width: int

    @property
    def templates(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "pools": self.pools,
                "pool_type": self.pool_type,
                "change_label": self.change_label,
                "change_state": self.change_state,
                "grid_width": self.grid_width,
                "grid_columns": self.grid_columns,
                "base_columns": self.base_columns,
                "stage_height": self.stage_height,
                "transition_arrows": self.transition_arrows,
                "transition_overlay": self.transition_overlay,
                "transition_overlay_width": self.transition_overlay_width,
            }
        )


@dataclass(frozen=True, slots=True)
class PoolPetPlacement:
    pet: PeakPetSnapshot
    historical: bool
    transition_id: int | None = None


GridSide = Literal["top", "bottom"]


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


def present_peak_pool(
    snapshot: PeakPoolRenderSnapshot,
    pool_type: str,
    assets: PeakPoolImageAssets,
) -> PeakPoolRenderDocument:
    """Lay out current and historical positions without performing I/O."""

    layout = _pool_grid_layout(snapshot)
    pools = _pool_documents(layout, assets, snapshot=snapshot)
    grid_width = layout.columns * CELL_WIDTH + (layout.columns - 1) * CELL_GAP
    stage_height, arrows = pool_transition_arrows(layout)
    overlay_width = grid_width + POOL_OVERHEAD
    return PeakPoolRenderDocument(
        pools=pools,
        pool_type=pool_type,
        change_label=(
            "大师池" if snapshot.master else ("专家池" if snapshot.expert else "竞技池")
        ),
        change_state=snapshot.change_state,
        grid_width=grid_width,
        grid_columns=layout.columns,
        base_columns=layout.base_columns,
        stage_height=stage_height,
        transition_arrows=arrows,
        transition_overlay=transition_overlay_uri(overlay_width, stage_height, arrows),
        transition_overlay_width=overlay_width,
        max_width=overlay_width + CONTAINER_PADDING + 20,
    )


async def render_peak_pool_document(
    render_html: HtmlTemplateRenderer,
    document: PeakPoolRenderDocument,
) -> bytes:
    return await render_html(
        template_path=[PEAK_POOL_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates=document.templates,
        max_width=document.max_width,
        allow_refit=False,
    )


def _pool_grid_layout(snapshot: PeakPoolRenderSnapshot) -> PoolGridLayout:
    positions: tuple[int | None, ...] = (
        (0, None) if snapshot.expert else (0, 2, 3, None)
    )
    if snapshot.master:
        costs = {pool.count for pool in snapshot.pools if pool.pets}
        costs.update(
            value
            for transition in snapshot.transitions
            for value in (transition.previous_limit, transition.current_limit)
            if value is not None
        )
        positions = tuple(sorted(costs, reverse=True))
        if any(
            transition.previous_limit is None or transition.current_limit is None
            for transition in snapshot.transitions
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
    result: dict[int | None, list[PeakPetSnapshot]] = {
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
                if pet.id not in current_ids:
                    result[position].append(pet)
                    current_ids.add(pet.id)
    for transition in snapshot.transitions:
        if transition.current_limit in result and transition.pet.id not in current_ids:
            result[transition.current_limit].append(transition.pet)
            current_ids.add(transition.pet.id)
    return result


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
                transition_index,
                pet,
                previous_position,
                current_position,
                position_indexes[previous_position],
                position_indexes[current_position],
                lane,
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
        _ceil_div(max_items, MAX_BASE_COLUMNS),
        _max_transition_boundary_rows(transition_lanes),
    )
    base_columns = max(1, _ceil_div(max_items, target_rows))
    lane_count = max(
        (transition.lane + 1 for transition in transition_lanes),
        default=0,
    )
    return PoolGridDimensions(base_columns, base_columns + lane_count)


def _max_transition_boundary_rows(
    transition_lanes: tuple[PoolTransitionLane, ...],
) -> int:
    endpoint_loads: dict[tuple[int | None, int], int] = {}
    for transition in transition_lanes:
        for position in (transition.previous_position, transition.current_position):
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
        previous_side: GridSide = (
            "bottom" if transition.previous_index < transition.current_index else "top"
        )
        current_side: GridSide = (
            "top" if transition.previous_index < transition.current_index else "bottom"
        )
        column = dimensions.base_columns + transition.lane
        previous_loads = edge_loads[(previous, previous_side)]
        current_loads = edge_loads[(current, current_side)]
        reserved[previous].append(
            ReservedPlacement(
                PoolPetPlacement(
                    transition.pet,
                    historical=True,
                    transition_id=transition.transition_index,
                ),
                previous_side,
                column,
                previous_loads[column],
            )
        )
        reserved[current].append(
            ReservedPlacement(
                PoolPetPlacement(
                    transition.pet,
                    historical=False,
                    transition_id=transition.transition_index,
                ),
                current_side,
                column,
                current_loads[column],
            )
        )
        previous_loads[column] += 1
        current_loads[column] += 1

    return PoolGridLayout(
        dimensions.base_columns,
        dimensions.columns,
        tuple(
            _place_pool_section(
                position,
                dimensions=dimensions,
                reserved=reserved[position],
                regular=regular[position],
                edge_loads=edge_loads,
            )
            for position in positions
        ),
    )


def _place_pool_section(
    position: int | None,
    *,
    dimensions: PoolGridDimensions,
    reserved: list[ReservedPlacement],
    regular: list[PoolPetPlacement],
    edge_loads: dict[tuple[int | None, GridSide], list[int]],
) -> PoolSectionLayout:
    if not reserved and not regular:
        return PoolSectionLayout(position, 0, ())
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
    return PoolSectionLayout(position, rows, tuple(slots))


def _pool_documents(
    layout: PoolGridLayout,
    assets: PeakPoolImageAssets,
    *,
    snapshot: PeakPoolRenderSnapshot,
) -> tuple[PeakPoolDocument, ...]:
    heads = assets.head_by_resource_id
    historical_heads = assets.historical_head_by_resource_id
    type_icons = assets.type_icon_by_id
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
    return tuple(
        PeakPoolDocument(
            label=(
                "未列入"
                if snapshot.master and section.position is None
                else (
                    f"{section.position} 点"
                    if snapshot.master
                    else _pool_position_label(
                        section.position,
                        expert=snapshot.expert,
                    )
                )
            ),
            current_count=current_counts[section.position],
            previous_count=(
                None
                if snapshot.change_state == "unavailable"
                else previous_counts[section.position]
            ),
            rows=section.rows,
            slots=tuple(
                None
                if placement is None
                else _pool_pet_document(
                    placement,
                    heads=heads,
                    historical_heads=historical_heads,
                    type_icons=type_icons,
                )
                for placement in section.slots
            ),
        )
        for section in layout.sections
    )


def _pool_pet_document(
    placement: PoolPetPlacement,
    *,
    heads: Mapping[int, str],
    historical_heads: Mapping[int, str],
    type_icons: Mapping[int, str],
) -> PeakPoolPetDocument:
    pet = placement.pet
    selected_heads = historical_heads if placement.historical else heads
    return PeakPoolPetDocument(
        pet.id,
        pet.name,
        selected_heads.get(pet.resource_id, ""),
        type_icons.get(pet.type_id, ""),
        placement.historical,
    )


def _pool_position_label(value: int | None, *, expert: bool) -> str:
    if value is None:
        return "不限"
    if expert:
        return "禁用"
    return f"限{value}"
