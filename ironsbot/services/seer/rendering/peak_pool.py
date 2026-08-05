# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation and HTML rendering for peak-pool documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ironsbot.services.seer.render_paths import (
    PEAK_POOL_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ironsbot.services.seer.peak import PeakPoolSnapshot

    from . import HtmlTemplateRenderer
    from .pet_image_assets import PetImageAssets

CELL_WIDTH = 100 + 2 * 2  # pet-cell width + border
CELL_GAP = 10
POOL_OVERHEAD = 18 * 2 + 1 * 2  # pool-section padding + border
CONTAINER_PADDING = 20 * 2
MAX_COLS = 10


@dataclass(frozen=True, slots=True)
class PeakPoolPetDocument:
    id: int
    name: str
    head_img: str
    type_icon: str


@dataclass(frozen=True, slots=True)
class PeakPoolDocument:
    id: int
    count: int
    pets: tuple[PeakPoolPetDocument, ...]


@dataclass(frozen=True, slots=True)
class PeakPoolRenderDocument:
    pools: tuple[PeakPoolDocument, ...]
    pool_type: str
    max_width: int

    @property
    def templates(self) -> Mapping[str, object]:
        return MappingProxyType(
            {"pools": self.pools, "pool_type": self.pool_type},
        )


def peak_pool_cache_key(
    pools: Sequence[PeakPoolSnapshot],
    pool_type: str,
) -> str:
    """Fingerprint all domain data that affects the rendered pool image."""
    values = tuple(
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
        for pool in pools
    )
    return hashlib.sha256(repr((pool_type, values)).encode()).hexdigest()


def present_peak_pool(
    pools: Sequence[PeakPoolSnapshot],
    pool_type: str,
    assets: PetImageAssets,
) -> PeakPoolRenderDocument:
    """Prepare a deterministic pool document without I/O or clock access."""
    head_icons = assets.pet_head_by_resource_id
    type_icons = assets.type_icon_by_id
    documents = tuple(
        PeakPoolDocument(
            id=pool.id,
            count=pool.count,
            pets=tuple(
                PeakPoolPetDocument(
                    id=pet.id,
                    name=pet.name,
                    head_img=head_icons[pet.resource_id],
                    type_icon=type_icons[pet.type_id],
                )
                for pet in pool.pets
            ),
        )
        for pool in pools
    )
    max_pets = max(len(pool.pets) for pool in documents)
    cols = min(max_pets, MAX_COLS)
    grid_width = cols * CELL_WIDTH + (cols - 1) * CELL_GAP
    return PeakPoolRenderDocument(
        pools=documents,
        pool_type=pool_type,
        max_width=grid_width + POOL_OVERHEAD + CONTAINER_PADDING + 20,
    )


async def render_peak_pool_document(
    render_html: HtmlTemplateRenderer,
    document: PeakPoolRenderDocument,
) -> bytes:
    """Render one prepared pool document without loading data or assets."""
    return await render_html(
        template_path=[PEAK_POOL_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates=document.templates,
        max_width=document.max_width,
        allow_refit=False,
    )
