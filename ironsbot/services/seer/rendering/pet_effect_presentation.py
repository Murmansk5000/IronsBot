# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation helpers for already-resolved pet special effects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.ai.analysis_parser import AnalyzeDescParser

if TYPE_CHECKING:
    from seerapi_models import PetORM

    from .custom_pet_models import SpecialEffectDict

DEFAULT_EFFECT_COLOR = "#f35555"


@dataclass(frozen=True, slots=True)
class PetSpecialEffectView:
    """One published special effect ready for the pet renderer."""

    name: str
    description: str | None
    glossary_id: int | None
    status_id: int | None
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SoulmarkIconAsset:
    """A pre-rendered soulmark icon published with SeerAPI data."""

    icon_id: int
    png: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class PetDerivedDisplayData:
    """Published pet facts consumed without renderer-side inference."""

    special_effects: tuple[PetSpecialEffectView, ...]
    soulmark_display_order: dict[int, int]
    soulmark_icons: dict[int, SoulmarkIconAsset]


def assign_special_effect_colors(
    pet: PetORM,
    effects: list[SpecialEffectDict],
) -> None:
    """Reuse the first official rich-text color for each resolved effect."""
    colors_by_name: dict[str, str] = {}
    names = {effect["name"] for effect in effects}
    if names:
        for description in _pet_effect_texts(pet):
            for segment in AnalyzeDescParser(description).segments:
                if not segment.colors:
                    continue
                for name in names:
                    if name in segment.text and name not in colors_by_name:
                        colors_by_name[name] = segment.colors[-1]

    for effect in effects:
        effect["color"] = colors_by_name.get(effect["name"], DEFAULT_EFFECT_COLOR)


def _pet_effect_texts(pet: PetORM) -> list[str]:
    texts: list[str] = []
    for skill_link in pet.skill_links:
        skill = skill_link.skill
        if skill.info:
            texts.append(str(skill.info))
        for effect in (*skill.skill_effect, *skill.friend_skill_effect):
            description = effect.analyze_info or effect.info
            if description:
                texts.append(str(description))
        if skill.hide_effect and skill.hide_effect.description:
            texts.append(str(skill.hide_effect.description))
    texts.extend(
        str(soulmark.analyze_desc or "") for soulmark in pet.soulmark
    )
    return texts
