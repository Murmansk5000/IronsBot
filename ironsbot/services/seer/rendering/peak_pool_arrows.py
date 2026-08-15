# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Protocol

from PIL import Image, ImageDraw

from ironsbot.services.seer.images import to_data_uri

if TYPE_CHECKING:
    from collections.abc import Sequence

CELL_WIDTH = 100 + 2 * 2  # pet-cell width + border
CELL_GAP = 0
CELL_STEP = CELL_WIDTH + CELL_GAP
POOL_GRID_LEFT = 1 + 18
POOL_GRID_TOP = 1 + 18 + 28 + 10 + 1 + 14
POOL_SECTION_FIXED_HEIGHT = POOL_GRID_TOP + 18 + 1
POOL_SECTION_MARGIN = 16
EMPTY_GRID_HEIGHT = 56


class _PoolPlacement(Protocol):
    @property
    def transition_id(self) -> int | None: ...

    @property
    def historical(self) -> bool: ...


class _PoolSection(Protocol):
    @property
    def rows(self) -> int: ...

    @property
    def slots(self) -> Sequence[_PoolPlacement | None]: ...


class PoolGridGeometry(Protocol):
    @property
    def columns(self) -> int: ...

    @property
    def sections(self) -> Sequence[_PoolSection]: ...


@dataclass(frozen=True, slots=True)
class _PlacementGeometry:
    x: int
    top: int
    bottom: int


@dataclass(frozen=True, slots=True)
class PoolTransitionArrow:
    transition_id: int
    x: int
    start_y: int
    line_end_y: int
    head_points: tuple[tuple[int, int], tuple[int, int], tuple[int, int]]


def pool_transition_arrows(
    layout: PoolGridGeometry,
) -> tuple[int, tuple[PoolTransitionArrow, ...]]:
    endpoints: dict[int, dict[bool, _PlacementGeometry]] = {}
    section_top = 0
    for section in layout.sections:
        grid_height = _pool_grid_height(section.rows)
        for slot_index, placement in enumerate(section.slots):
            if placement is None or placement.transition_id is None:
                continue
            row, column = divmod(slot_index, layout.columns)
            top = section_top + POOL_GRID_TOP + row * CELL_STEP
            endpoints.setdefault(placement.transition_id, {})[
                placement.historical
            ] = _PlacementGeometry(
                x=POOL_GRID_LEFT + column * CELL_STEP + CELL_WIDTH // 2,
                top=top,
                bottom=top + CELL_WIDTH,
            )
        section_top += (
            POOL_SECTION_FIXED_HEIGHT
            + grid_height
            + POOL_SECTION_MARGIN
        )

    arrows = tuple(
        _pool_transition_arrow(transition_id, pair[True], pair[False])
        for transition_id, pair in sorted(endpoints.items())
        if True in pair and False in pair
    )
    return section_top, arrows


def transition_overlay_uri(
    width: int,
    height: int,
    arrows: tuple[PoolTransitionArrow, ...],
) -> str:
    if not arrows:
        return ""
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    drawing = ImageDraw.Draw(overlay)
    for arrow in arrows:
        _draw_vertical_dashes(
            drawing,
            x=arrow.x,
            start_y=arrow.start_y,
            end_y=arrow.line_end_y,
        )
        drawing.polygon(arrow.head_points, fill=(255, 255, 255, 255))
    output = BytesIO()
    overlay.save(output, format="PNG")
    return to_data_uri(output.getvalue())


def _pool_grid_height(rows: int) -> int:
    if rows == 0:
        return EMPTY_GRID_HEIGHT
    return rows * CELL_WIDTH + (rows - 1) * CELL_GAP


def _pool_transition_arrow(
    transition_id: int,
    previous: _PlacementGeometry,
    current: _PlacementGeometry,
) -> PoolTransitionArrow:
    downward = previous.top < current.top
    x = (previous.x + current.x) // 2
    start_y = previous.bottom + 3 if downward else previous.top - 3
    tip_y = current.top - 3 if downward else current.bottom + 3
    line_end_y = tip_y - 9 if downward else tip_y + 9
    head_base_y = tip_y - 10 if downward else tip_y + 10
    return PoolTransitionArrow(
        transition_id=transition_id,
        x=x,
        start_y=start_y,
        line_end_y=line_end_y,
        head_points=(
            (x, tip_y),
            (x - 6, head_base_y),
            (x + 6, head_base_y),
        ),
    )


def _draw_vertical_dashes(
    drawing: ImageDraw.ImageDraw,
    *,
    x: int,
    start_y: int,
    end_y: int,
) -> None:
    top, bottom = sorted((start_y, end_y))
    for dash_top in range(top, bottom + 1, 14):
        drawing.line(
            (x, dash_top, x, min(dash_top + 8, bottom)),
            fill=(255, 255, 255, 255),
            width=3,
        )
