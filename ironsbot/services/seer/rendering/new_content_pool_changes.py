# SPDX-License-Identifier: GPL-3.0-or-later
"""Build compact avatar previews for weekly peak-pool changes."""

from __future__ import annotations

import asyncio
from typing import TypedDict

from ironsbot.services.seer.images import (
    ImageSourceError,
    SeerImageSource,
    to_data_uri,
)
from ironsbot.services.seer.new_content import (
    CATEGORY_NAMES,
    NewContentCategory,
    NewContentItem,
)


class PoolChangePetDict(TypedDict):
    entity_id: int
    image: str | None


class PoolChangeMatrixRowDict(TypedDict):
    label: str
    cells: tuple[tuple[PoolChangePetDict, ...], ...]


class PoolChangeDirectionRowDict(TypedDict):
    direction: str
    pets: tuple[PoolChangePetDict, ...]


class PoolChangePreviewDict(TypedDict):
    kind: str
    title: str
    headers: tuple[str, ...]
    matrix_rows: tuple[PoolChangeMatrixRowDict, ...]
    direction_rows: tuple[PoolChangeDirectionRowDict, ...]
    other_rows: tuple[PoolChangeDirectionRowDict, ...]


_POOL_LIMITS: tuple[int | None, ...] = (0, 2, 3, None)


def pool_change_preview(
    category: NewContentCategory,
    items: tuple[NewContentItem, ...],
    images: dict[tuple[NewContentCategory, int], str | None] | None = None,
) -> PoolChangePreviewDict:
    grouped: dict[
        tuple[int | str | None, int | str | None],
        list[PoolChangePetDict],
    ] = {}
    images = images or {}
    for item in items:
        transition = (
            _pool_limit_key(item.payload.get("previous_limit")),
            _pool_limit_key(item.payload.get("current_limit")),
        )
        grouped.setdefault(transition, []).append(
            PoolChangePetDict(
                entity_id=item.entity_id,
                image=images.get((category, item.entity_id)),
            )
        )

    if category == "peak_pool":
        known_transitions = {
            (previous, current)
            for previous in _POOL_LIMITS
            for current in _POOL_LIMITS
        }
        matrix_rows = tuple(
            PoolChangeMatrixRowDict(
                label=f"从{_pool_limit_label(previous)}",
                cells=tuple(
                    tuple(grouped.get((previous, current), ()))
                    for current in _POOL_LIMITS
                ),
            )
            for previous in _POOL_LIMITS
        )
        direction_rows: tuple[PoolChangeDirectionRowDict, ...] = ()
    else:
        known_transitions = {(None, 0), (0, None)}
        matrix_rows = ()
        direction_rows = tuple(
            PoolChangeDirectionRowDict(
                direction=_pool_transition_label(previous, current),
                pets=tuple(grouped.get((previous, current), ())),
            )
            for previous, current in ((None, 0), (0, None))
        )

    other_rows = tuple(
        PoolChangeDirectionRowDict(
            direction=_pool_transition_label(previous, current),
            pets=tuple(pets),
        )
        for (previous, current), pets in sorted(
            (
                (transition, pets)
                for transition, pets in grouped.items()
                if transition not in known_transitions
            ),
            key=lambda entry: _pool_transition_label(*entry[0]),
        )
    )
    return PoolChangePreviewDict(
        kind="standard" if category == "peak_pool" else "expert",
        title=(
            f"{CATEGORY_NAMES[category]}｜{len(items)} 只"
            if items
            else f"{CATEGORY_NAMES[category]}｜本周未变化"
        ),
        headers=tuple(f"到{_pool_limit_label(limit)}" for limit in _POOL_LIMITS),
        matrix_rows=matrix_rows,
        direction_rows=direction_rows,
        other_rows=other_rows,
    )


async def load_pool_change_images(
    images: SeerImageSource,
    items: tuple[NewContentItem, ...],
) -> dict[tuple[NewContentCategory, int], str | None]:
    image_results = await asyncio.gather(
        *(_pool_pet_image(images, item) for item in items)
    )
    return {
        (item.category, item.entity_id): image
        for item, image in zip(items, image_results, strict=True)
    }


def _pool_limit_key(value: object) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return f"未知（{value!r}）"
    if not isinstance(value, (int, str)):
        return f"未知（{value}）"
    try:
        return int(value)
    except (TypeError, ValueError):
        return f"未知（{value}）"


def _pool_limit_label(value: int | str | None) -> str:
    if value is None:
        return "不限"
    if isinstance(value, int):
        return f"限{value}"
    return value


def _pool_transition_label(
    previous: int | str | None,
    current: int | str | None,
) -> str:
    return f"{_pool_limit_label(previous)} → {_pool_limit_label(current)}"


async def _pool_pet_image(
    images: SeerImageSource,
    item: NewContentItem,
) -> str | None:
    try:
        data = await images.fetch("pet_head", str(item.entity_id), fallback=False)
    except (ImageSourceError, RuntimeError, TypeError, ValueError):
        return None
    return to_data_uri(data)
