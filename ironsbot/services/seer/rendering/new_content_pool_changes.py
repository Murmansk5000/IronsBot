# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation models for weekly peak-pool changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.seer.new_content import CATEGORY_NAMES

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.seer.new_content import NewContentCategory, NewContentItem


@dataclass(frozen=True, slots=True)
class PoolChangePet:
    entity_id: int
    image: str | None


@dataclass(frozen=True, slots=True)
class PoolChangeMatrixRow:
    label: str
    cells: tuple[tuple[PoolChangePet, ...], ...]


@dataclass(frozen=True, slots=True)
class PoolChangeDirectionRow:
    direction: str
    pets: tuple[PoolChangePet, ...]


@dataclass(frozen=True, slots=True)
class PoolChangePreview:
    kind: str
    title: str
    headers: tuple[str, ...]
    matrix_rows: tuple[PoolChangeMatrixRow, ...]
    direction_rows: tuple[PoolChangeDirectionRow, ...]
    other_rows: tuple[PoolChangeDirectionRow, ...]


_POOL_LIMITS: tuple[int | None, ...] = (0, 2, 3, None)


def present_pool_changes(
    category: NewContentCategory,
    items: tuple[NewContentItem, ...],
    images: Mapping[tuple[NewContentCategory, int], str | None],
) -> PoolChangePreview:
    grouped: dict[tuple[int | str | None, int | str | None], list[PoolChangePet]] = {}
    for item in items:
        transition = (
            _limit_key(item.payload.get("previous_limit")),
            _limit_key(item.payload.get("current_limit")),
        )
        grouped.setdefault(transition, []).append(
            PoolChangePet(item.entity_id, images.get((category, item.entity_id)))
        )

    master = category == "peak_master_pool"
    limits = _POOL_LIMITS
    label = _master_cost_label if master else _limit_label
    if master:
        costs = {
            value
            for transition in grouped
            for value in transition
            if isinstance(value, int) and value >= 0
        }
        limits = tuple(sorted(costs, reverse=True))
        if any(None in transition for transition in grouped):
            limits = (*limits, None)

    if category in {"peak_pool", "peak_master_pool"}:
        known = {(previous, current) for previous in limits for current in limits}
        matrix_rows = tuple(
            PoolChangeMatrixRow(
                f"从{label(previous)}",
                tuple(
                    tuple(grouped.get((previous, current), ())) for current in limits
                ),
            )
            for previous in limits
        )
        direction_rows: tuple[PoolChangeDirectionRow, ...] = ()
        kind = "master" if master else "standard"
    else:
        known = {(None, 0), (0, None)}
        matrix_rows = ()
        direction_rows = tuple(
            PoolChangeDirectionRow(
                _transition_label(previous, current),
                tuple(grouped.get((previous, current), ())),
            )
            for previous, current in ((None, 0), (0, None))
        )
        kind = "expert"

    other_rows = tuple(
        PoolChangeDirectionRow(
            f"{label(transition[0])} → {label(transition[1])}", tuple(pets)
        )
        for transition, pets in sorted(
            (
                (transition, pets)
                for transition, pets in grouped.items()
                if transition not in known
            ),
            key=lambda entry: _transition_label(*entry[0]),
        )
    )
    title = (
        f"{CATEGORY_NAMES[category]}｜{len(items)} 只"
        if items
        else f"{CATEGORY_NAMES[category]}｜本周未变化"
    )
    return PoolChangePreview(
        kind=kind,
        title=title,
        headers=tuple(f"到{label(limit)}" for limit in limits),
        matrix_rows=matrix_rows,
        direction_rows=direction_rows,
        other_rows=other_rows,
    )


def _limit_key(value: object) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | str):
        return f"未知（{value!r}）"
    try:
        return int(value)
    except ValueError:
        return f"未知（{value}）"


def _limit_label(value: int | str | None) -> str:
    if value is None:
        return "不限"
    return f"限{value}" if isinstance(value, int) else value


def _master_cost_label(value: int | str | None) -> str:
    return "未列入" if value is None else f"{value} 点"


def _transition_label(previous: int | str | None, current: int | str | None) -> str:
    return f"{_limit_label(previous)} → {_limit_label(current)}"
