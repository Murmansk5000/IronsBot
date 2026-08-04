# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation and HTML rendering for type-matchup documents."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from ironsbot.services.seer.render_paths import TYPE_MATCHUP_TEMPLATE_PATH

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.seer.type_calc import (
        TypeCombinationSnapshot,
        TypeMatchup,
    )

    from . import HtmlTemplateRenderer

GRID_COLUMNS = 10
CELL_SIZE = 72
CELL_GAP = 6
SECTION_OVERHEAD = 16 * 2 + 1 * 2  # section padding + border
CONTAINER_PADDING = 20 * 2
GRID_WIDTH = GRID_COLUMNS * CELL_SIZE + (GRID_COLUMNS - 1) * CELL_GAP
MAX_WIDTH = GRID_WIDTH + SECTION_OVERHEAD + CONTAINER_PADDING


@dataclass(frozen=True, slots=True)
class TypeMatchupAssets:
    """Data-URI assets detached from the image source."""

    icons: tuple[tuple[int, str], ...]
    target_icon: str
    target_icon_secondary: str | None

    @property
    def icon_by_id(self) -> Mapping[int, str]:
        return MappingProxyType(dict(self.icons))


@dataclass(frozen=True, slots=True)
class TypeMatchupItemDocument:
    icon: str
    name: str
    multiplier: float


@dataclass(frozen=True, slots=True)
class TypeMatchupRenderDocument:
    type_name: str
    type_icon: str
    type_icon_secondary: str | None
    attack_items: tuple[TypeMatchupItemDocument, ...]
    defense_items: tuple[TypeMatchupItemDocument, ...]

    @property
    def templates(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "type_name": self.type_name,
                "type_icon": self.type_icon,
                "type_icon_secondary": self.type_icon_secondary,
                "attack_items": self.attack_items,
                "defense_items": self.defense_items,
                "cell_size": CELL_SIZE,
                "cell_gap": CELL_GAP,
            }
        )


def present_type_matchup(
    matchup: TypeMatchup,
    assets: TypeMatchupAssets,
) -> TypeMatchupRenderDocument:
    """Create a deterministic template document without I/O or data access."""
    icons = assets.icon_by_id
    return TypeMatchupRenderDocument(
        type_name=matchup.target.name,
        type_icon=assets.target_icon,
        type_icon_secondary=assets.target_icon_secondary,
        attack_items=_present_items(matchup.attack_table, icons),
        defense_items=_present_items(matchup.defense_table, icons),
    )


def _present_items(
    values: list[tuple[TypeCombinationSnapshot, float]],
    icons: Mapping[int, str],
) -> tuple[TypeMatchupItemDocument, ...]:
    return tuple(
        TypeMatchupItemDocument(
            icon=icons[combination.id],
            name=combination.name,
            multiplier=multiplier,
        )
        for combination, multiplier in sorted(
            values,
            key=lambda value: value[1],
            reverse=True,
        )
    )


async def render_type_matchup_document(
    render_html: HtmlTemplateRenderer,
    document: TypeMatchupRenderDocument,
) -> bytes:
    """Render a prepared document without reading data or fetching assets."""
    return await render_html(
        template_path=TYPE_MATCHUP_TEMPLATE_PATH,
        template_name="template.html.j2",
        templates=document.templates,
        max_width=MAX_WIDTH,
        allow_refit=False,
    )
