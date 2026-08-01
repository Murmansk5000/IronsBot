# SPDX-License-Identifier: MIT
"""Read official contract-partner data embedded in the IronsBot data release."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.orm import Session

PET_PARTNER_GROUP_TABLE = "pet_partner_group"
PET_PARTNER_MEMBER_TABLE = "pet_partner_member"
PET_PARTNER_UPGRADE_TABLE = "pet_partner_upgrade"
SKILL_IN_PET_TABLE = "skillinpetorm"
SKILL_ACTIVATION_ITEM_TABLE = "skill_activation_item"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PetPartnerMember:
    pet_id: int
    name: str


@dataclass(frozen=True, slots=True)
class PetPartnerSkillItem:
    item_id: int
    name: str
    quantity: int


@dataclass(frozen=True, slots=True)
class PetPartnerSkill:
    skill_id: int
    name: str
    activation_item: PetPartnerSkillItem | None


@dataclass(frozen=True, slots=True)
class PetPartner:
    group_id: int
    name: str
    cost_item_id: int
    cost_item_name: str
    cost_item_quantity: int
    members: tuple[PetPartnerMember, ...]
    before_description: str
    after_description: str
    skill: PetPartnerSkill | None


def _mapping(row: Any) -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", row._mapping if hasattr(row, "_mapping") else row)


def load_pet_partner(session: Session, pet_id: int) -> PetPartner | None:
    """Load one pet's official contract-partner group.

    The partner payload's before/after description columns are directionally
    inverted, so normalize them before exposing the logical display order.

    The release may predate this enrichment. In that case the card simply
    omits the section instead of making unrelated pet queries fail.
    """

    if pet_id <= 0:
        return None

    statement = text(
        f"""
        SELECT
            partner_group.group_id,
            partner_group.name AS group_name,
            partner_group.cost_item_id,
            COALESCE(NULLIF(cost_item.name, ''), partner_group.cost_item_name)
                AS cost_item_name,
            partner_group.cost_item_quantity,
            -- ConfigPackage labels these two values in reverse display order.
            COALESCE(partner_upgrade.after_description, '') AS before_description,
            COALESCE(partner_upgrade.before_description, '') AS after_description,
            partner_upgrade.skill_id,
            COALESCE(skill.name, '') AS skill_name,
            activation_item.id AS activation_item_id,
            COALESCE(activation_item.name, '') AS activation_item_name,
            COALESCE(activation_item.item_number, 1) AS activation_item_quantity
        FROM {PET_PARTNER_MEMBER_TABLE} AS current_member
        JOIN {PET_PARTNER_GROUP_TABLE} AS partner_group
            ON partner_group.group_id = current_member.group_id
        LEFT JOIN item AS cost_item
            ON cost_item.id = partner_group.cost_item_id
        LEFT JOIN {PET_PARTNER_UPGRADE_TABLE} AS partner_upgrade
            ON partner_upgrade.pet_id = current_member.pet_id
        LEFT JOIN skill
            ON skill.id = partner_upgrade.skill_id
        LEFT JOIN {SKILL_IN_PET_TABLE} AS skill_link
            ON skill_link.pet_id = current_member.pet_id
            AND skill_link.skill_id = partner_upgrade.skill_id
        LEFT JOIN {SKILL_ACTIVATION_ITEM_TABLE} AS activation_item
            ON activation_item.id = skill_link.skill_activation_item_id
        WHERE current_member.pet_id = :pet_id
        ORDER BY partner_group.group_id
        LIMIT 1
        """
    )
    members_statement = text(
        f"""
        SELECT
            partner_member.pet_id,
            COALESCE(NULLIF(pet.name, ''), '精灵' || partner_member.pet_id) AS name
        FROM {PET_PARTNER_MEMBER_TABLE} AS partner_member
        LEFT JOIN pet
            ON pet.id = partner_member.pet_id
        WHERE partner_member.group_id = :group_id
        ORDER BY partner_member.display_order, partner_member.pet_id
        """
    )
    try:
        row = session.execute(statement, {"pet_id": pet_id}).first()
        if row is None:
            return None
        values = _mapping(row)
        member_rows = session.execute(
            members_statement,
            {"group_id": int(values["group_id"])},
        ).all()
    except SQLAlchemyError:
        logger.debug(
            "pet partner data is unavailable in the current SQLite release",
            exc_info=True,
        )
        return None

    skill_id = int(values["skill_id"] or 0)
    activation_item_id = int(values["activation_item_id"] or 0)
    activation_item_name = str(values["activation_item_name"] or "").strip()
    activation_item = (
        PetPartnerSkillItem(
            item_id=activation_item_id,
            name=activation_item_name,
            quantity=max(1, int(values["activation_item_quantity"] or 1)),
        )
        if activation_item_id > 0 and activation_item_name
        else None
    )
    skill_name = str(values["skill_name"] or "").strip()
    skill = (
        PetPartnerSkill(
            skill_id=skill_id,
            name=skill_name or f"技能{skill_id}",
            activation_item=activation_item,
        )
        if skill_id > 0
        else None
    )
    return PetPartner(
        group_id=int(values["group_id"]),
        name=str(values["group_name"] or "").strip(),
        cost_item_id=int(values["cost_item_id"]),
        cost_item_name=str(values["cost_item_name"] or "").strip(),
        cost_item_quantity=int(values["cost_item_quantity"]),
        members=tuple(
            PetPartnerMember(
                pet_id=int(_mapping(member_row)["pet_id"]),
                name=str(_mapping(member_row)["name"] or "").strip(),
            )
            for member_row in member_rows
        ),
        before_description=str(values["before_description"] or "").strip(),
        after_description=str(values["after_description"] or "").strip(),
        skill=skill,
    )
