# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation and HTML rendering for peak-pool vote documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ironsbot.services.seer.render_paths import (
    PEAK_POOL_VOTE_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ironsbot.services.seer.peak import (
        PeakPetSnapshot,
        PeakVoteItemSnapshot,
        PeakVotePoolInput,
    )

    from . import HtmlTemplateRenderer
    from .pet_image_assets import PetImageAssets

TABLE_WIDTH = 400
CONTAINER_PADDING = 20 * 2


@dataclass(frozen=True, slots=True)
class PeakVoteRankDocument:
    rank: int
    pet_id: int
    name: str
    score: int
    head_img: str
    type_icon: str


@dataclass(frozen=True, slots=True)
class PeakVotePoolDocument:
    title: str
    ranks: tuple[PeakVoteRankDocument, ...]


@dataclass(frozen=True, slots=True)
class PeakPoolVoteRenderDocument:
    pools: tuple[PeakVotePoolDocument, ...]
    generated_at: str

    @property
    def templates(self) -> Mapping[str, object]:
        return MappingProxyType(
            {"pools": self.pools, "generated_at": self.generated_at},
        )


def peak_pool_vote_cache_key(
    pools: Sequence[PeakVotePoolInput],
    generated_at: str,
) -> str:
    """Fingerprint every value that changes a rendered peak-vote image."""
    values = tuple(
        (
            pool.title,
            tuple((item.id, item.name, item.score) for item in pool.items),
            tuple(
                (pet.id, pet.name, pet.resource_id, pet.type_id)
                for pet in pool.pets
            ),
        )
        for pool in pools
    )
    return hashlib.sha256(repr((values, generated_at)).encode()).hexdigest()


def present_peak_pool_vote(
    pools: Sequence[PeakVotePoolInput],
    generated_at: str,
    assets: PetImageAssets,
) -> PeakPoolVoteRenderDocument:
    """Prepare a deterministic vote document without I/O or clock access."""
    pet_map = {
        pet.id: pet
        for pool in pools
        for pet in pool.pets
    }
    head_icons = assets.pet_head_by_resource_id
    type_icons = assets.type_icon_by_id
    documents = tuple(
        PeakVotePoolDocument(
            title=pool.title,
            ranks=tuple(
                _present_rank(
                    rank=index,
                    item=item,
                    pet_map=pet_map,
                    head_icons=head_icons,
                    type_icons=type_icons,
                )
                for index, item in enumerate(pool.items, 1)
            ),
        )
        for pool in pools
    )
    return PeakPoolVoteRenderDocument(
        pools=documents,
        generated_at=generated_at,
    )


def _present_rank(
    *,
    rank: int,
    item: PeakVoteItemSnapshot,
    pet_map: Mapping[int, PeakPetSnapshot],
    head_icons: Mapping[int, str],
    type_icons: Mapping[int, str],
) -> PeakVoteRankDocument:
    pet = pet_map.get(item.id)
    if pet is None:
        return PeakVoteRankDocument(
            rank=rank,
            pet_id=item.id,
            name=item.name,
            score=item.score,
            head_img="",
            type_icon="",
        )
    return PeakVoteRankDocument(
        rank=rank,
        pet_id=item.id,
        name=pet.name,
        score=item.score,
        head_img=head_icons[pet.resource_id],
        type_icon=type_icons[pet.type_id],
    )


async def render_peak_pool_vote_document(
    render_html: HtmlTemplateRenderer,
    document: PeakPoolVoteRenderDocument,
) -> bytes:
    """Render one prepared vote document without loading data or assets."""
    return await render_html(
        template_path=[PEAK_POOL_VOTE_TEMPLATE_PATH, SHARED_TEMPLATE_PATH],
        template_name="template.html.j2",
        templates=document.templates,
        max_width=TABLE_WIDTH + CONTAINER_PADDING + 20,
        allow_refit=False,
    )
