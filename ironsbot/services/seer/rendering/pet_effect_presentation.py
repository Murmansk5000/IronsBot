# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure presentation helpers for already-resolved pet special effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.ai.analysis_parser import AnalyzeDescParser

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .custom_pet_models import SpecialEffectDict

DEFAULT_EFFECT_COLOR = "#f35555"


def assign_special_effect_colors(
    effects: list[SpecialEffectDict],
    rich_texts: Iterable[str],
) -> None:
    """Reuse the first official rich-text color for each resolved effect.

    The repository supplies all source text before this function runs, keeping
    presentation independent of ORM objects and lazy relationships.
    """
    colors_by_name: dict[str, str] = {}
    names = {effect["name"] for effect in effects}
    if names:
        for description in rich_texts:
            for segment in AnalyzeDescParser(description).segments:
                if not segment.colors:
                    continue
                for name in names:
                    if name in segment.text and name not in colors_by_name:
                        colors_by_name[name] = segment.colors[-1]

    for effect in effects:
        effect["color"] = colors_by_name.get(effect["name"], DEFAULT_EFFECT_COLOR)
