# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation and HTML rendering for peak pet-rank documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ironsbot.services.seer.render_paths import (
    PEAK_PET_RANK_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.seer.peak import (
        PeakPetBanSnapshot,
        PeakPetPickSnapshot,
        PeakPetRankRenderInput,
        PeakPetSnapshot,
    )

    from . import HtmlTemplateRenderer
    from .peak_assets import PeakRenderAssets

TABLE_WIDTH = 580
CONTAINER_PADDING = 20 * 2


@dataclass(frozen=True, slots=True)
class PeakPetPickDocument:
    rank: int
    pet_id: int
    name: str
    count: int
    win: int
    win_rate: float
    head_img: str
    type_icon: str


@dataclass(frozen=True, slots=True)
class PeakPetBanDocument:
    rank: int
    pet_id: int
    name: str
    score: int
    head_img: str
    type_icon: str


@dataclass(frozen=True, slots=True)
class PeakPetRankRenderDocument:
    title: str
    pick_ranks: tuple[PeakPetPickDocument, ...]
    ban_ranks: tuple[PeakPetBanDocument, ...]

    @property
    def templates(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "title": self.title,
                "pick_ranks": self.pick_ranks,
                "ban_ranks": self.ban_ranks,
            },
        )


def peak_pet_rank_cache_key(input_: PeakPetRankRenderInput) -> str:
    """Fingerprint every domain field that changes a pet-rank image."""
    values = (
        input_.title,
        tuple((item.id, item.count, item.win) for item in input_.pick_items),
        tuple((item.id, item.name, item.score) for item in input_.ban_items),
        tuple(
            (pet.id, pet.name, pet.resource_id, pet.type_id)
            for pet in input_.pets
        ),
    )
    return hashlib.sha256(repr(values).encode()).hexdigest()


def present_peak_pet_rank(
    input_: PeakPetRankRenderInput,
    assets: PeakRenderAssets,
) -> PeakPetRankRenderDocument:
    """Prepare a deterministic pet-rank document without I/O or clock access."""
    pet_map = {pet.id: pet for pet in input_.pets}
    head_icons = assets.pet_head_by_resource_id
    type_icons = assets.type_icon_by_id
    return PeakPetRankRenderDocument(
        title=input_.title,
        pick_ranks=tuple(
            _present_pick_rank(
                rank=index,
                item=item,
                pet=pet_map.get(item.id),
                head_icons=head_icons,
                type_icons=type_icons,
            )
            for index, item in enumerate(input_.pick_items, 1)
        ),
        ban_ranks=tuple(
            _present_ban_rank(
                rank=index,
                item=item,
                pet=pet_map.get(item.id),
                head_icons=head_icons,
                type_icons=type_icons,
            )
            for index, item in enumerate(input_.ban_items, 1)
        ),
    )


def _present_pick_rank(
    *,
    rank: int,
    item: PeakPetPickSnapshot,
    pet: PeakPetSnapshot | None,
    head_icons: Mapping[int, str],
    type_icons: Mapping[int, str],
) -> PeakPetPickDocument:
    name, head_img, type_icon = _pet_display(
        pet,
        str(item.id),
        head_icons,
        type_icons,
    )
    return PeakPetPickDocument(
        rank=rank,
        pet_id=item.id,
        name=name,
        count=item.count,
        win=item.win,
        win_rate=item.win_rate,
        head_img=head_img,
        type_icon=type_icon,
    )


def _present_ban_rank(
    *,
    rank: int,
    item: PeakPetBanSnapshot,
    pet: PeakPetSnapshot | None,
    head_icons: Mapping[int, str],
    type_icons: Mapping[int, str],
) -> PeakPetBanDocument:
    name, head_img, type_icon = _pet_display(
        pet,
        item.name,
        head_icons,
        type_icons,
    )
    return PeakPetBanDocument(
        rank=rank,
        pet_id=item.id,
        name=name,
        score=item.score,
        head_img=head_img,
        type_icon=type_icon,
    )


def _pet_display(
    pet: PeakPetSnapshot | None,
    fallback_name: str,
    head_icons: Mapping[int, str],
    type_icons: Mapping[int, str],
) -> tuple[str, str, str]:
    if pet is None:
        return fallback_name, "", ""
    return (
        pet.name,
        head_icons[pet.resource_id],
        type_icons[pet.type_id],
    )


async def render_peak_pet_rank_document(
    render_html: HtmlTemplateRenderer,
    document: PeakPetRankRenderDocument,
) -> bytes:
    """Render one prepared pet-rank document without loading data or assets."""
    return await render_html(
        template_path=[PEAK_PET_RANK_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates=document.templates,
        max_width=TABLE_WIDTH + CONTAINER_PADDING + 20,
        allow_refit=False,
    )
