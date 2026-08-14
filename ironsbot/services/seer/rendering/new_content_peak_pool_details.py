# SPDX-License-Identifier: GPL-3.0-or-later
"""Build one new-content row for an official competitive-pool change."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .new_content_skill_details import NewContentItemDetails

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.new_content import NewContentItem


def peak_pool_limit_text(value: object) -> str:
    if value is None:
        return "不限"
    try:
        return f"限{int(value)}"
    except (TypeError, ValueError):
        return "未知"


def peak_pool_details(
    data: SeerDataAccess,
    item: NewContentItem,
) -> NewContentItemDetails:
    previous_limit = peak_pool_limit_text(item.payload.get("previous_limit"))
    current_limit = peak_pool_limit_text(item.payload.get("current_limit"))
    with data.get(data.pet, item.entity_id) as pet:
        if pet is None:
            return NewContentItemDetails(
                metadata=f"修改｜精灵 ID：{item.entity_id}",
                description=f"{previous_limit} → {current_limit}",
            )
        return NewContentItemDetails(
            metadata=f"精灵 ID：{pet.id}",
            description=f"{previous_limit} → {current_limit}",
            type_id=int(pet.type.id),
            gender_id=int(pet.gender.id),
            type_name=str(pet.type.name),
            gender_name=str(pet.gender.name),
        )
