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

    if category == "peak_pool":
        known = {
            (previous, current) for previous in _POOL_LIMITS for current in _POOL_LIMITS
        }
        matrix_rows = tuple(
            PoolChangeMatrixRow(
                f"从{_limit_label(previous)}",
                tuple(
                    tuple(grouped.get((previous, current), ()))
                    for current in _POOL_LIMITS
                ),
            )
            for previous in _POOL_LIMITS
        )
        direction_rows: tuple[PoolChangeDirectionRow, ...] = ()
        kind = "standard"
    elif category == "peak_master_pool":
        known = set(grouped)
        matrix_rows = ()
        direction_rows = tuple(
            PoolChangeDirectionRow(
                f"{_master_cost_label(previous)} → {_master_cost_label(current)}",
                tuple(pets),
            )
            for (previous, current), pets in sorted(
                grouped.items(), key=lambda entry: str(entry[0])
            )
        )
        kind = "master"
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
        PoolChangeDirectionRow(_transition_label(*transition), tuple(pets))
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
        headers=tuple(f"到{_limit_label(limit)}" for limit in _POOL_LIMITS),
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
