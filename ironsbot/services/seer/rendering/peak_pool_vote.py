# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation and HTML rendering for peak-pool vote documents."""

from __future__ import annotations

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

TABLE_WIDTH = 900
CONTAINER_PADDING = 20 * 2


@dataclass(frozen=True, slots=True)
class PeakVoteRankDocument:
    rank: int
    pet_id: int
    name: str
    score: int
    percentage: int
    head_img: str
    type_icon: str


@dataclass(frozen=True, slots=True)
class PeakVotePoolDocument:
    title: str
    period: str
    total_votes: int
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


def present_peak_pool_vote(
    pools: Sequence[PeakVotePoolInput],
    generated_at: str,
    assets: PetImageAssets,
) -> PeakPoolVoteRenderDocument:
    """Prepare a deterministic vote document without I/O or clock access."""
    pet_map = {pet.id: pet for pool in pools for pet in pool.pets}
    documents = []
    for pool in pools:
        total_votes = sum(max(item.score, 0) for item in pool.items)
        documents.append(
            PeakVotePoolDocument(
                title=pool.title,
                period=pool.period,
                total_votes=total_votes,
                ranks=tuple(
                    _present_rank(
                        rank=index,
                        item=item,
                        total_votes=total_votes,
                        pet_map=pet_map,
                        assets=assets,
                    )
                    for index, item in enumerate(pool.items, 1)
                ),
            )
        )
    return PeakPoolVoteRenderDocument(
        pools=tuple(documents),
        generated_at=generated_at,
    )


def _present_rank(
    *,
    rank: int,
    item: PeakVoteItemSnapshot,
    total_votes: int,
    pet_map: Mapping[int, PeakPetSnapshot],
    assets: PetImageAssets,
) -> PeakVoteRankDocument:
    percentage = round(max(item.score, 0) / total_votes * 100) if total_votes else 0
    pet = pet_map.get(item.id)
    if pet is None:
        return PeakVoteRankDocument(
            rank=rank,
            pet_id=item.id,
            name=item.name,
            score=item.score,
            percentage=percentage,
            head_img="",
            type_icon="",
        )
    return PeakVoteRankDocument(
        rank=rank,
        pet_id=item.id,
        name=pet.name,
        score=item.score,
        percentage=percentage,
        head_img=assets.pet_head_by_resource_id[pet.resource_id],
        type_icon=assets.type_icon_by_id[pet.type_id],
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
