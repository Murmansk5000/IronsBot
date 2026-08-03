# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared row facts for the release menu and skill projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .custom_pet_models import SkillDict


@dataclass(frozen=True, slots=True)
class _ItemDetails:
    """Small, category-specific facts shown beside a weekly content thumbnail."""

    metadata: str
    description: str
    side_title: str = ""
    side_description: str = ""
    stats: tuple[tuple[str, str], ...] = ()
    stats_layout: str = "inline"
    stats_total: str = ""
    type_id: int | None = None
    gender_id: int | None = None
    type_name: str = ""
    gender_name: str = ""
    skill: SkillDict | None = None
    friend_skill: SkillDict | None = None
