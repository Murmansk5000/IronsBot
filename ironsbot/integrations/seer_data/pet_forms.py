# SPDX-License-Identifier: MIT
"""Published official display-form facts; never infer families from numeric IDs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlmodel import Session

SKIN_FORM_STRIDE = 100000


@dataclass(frozen=True, slots=True)
class PetFormCatalog:
    resources: dict[tuple[int, int, int], int]
    members: frozenset[tuple[int, int]]

    def shares_skin(self, pet_id: int, owner_id: int) -> bool:
        if owner_id <= 0:
            return False
        if pet_id == owner_id:
            return True
        return any(
            (canonical, owner_id) in self.members
            for canonical, member in self.members
            if member == pet_id
        )

    def resource(self, pet_id: int, encoded_skin_id: int) -> int | None:
        form_index, skin_id = divmod(encoded_skin_id, SKIN_FORM_STRIDE)
        if form_index <= 0:
            return None
        return self.resources.get((0 if skin_id else pet_id, skin_id, form_index))


def load_pet_forms(session: Session) -> PetFormCatalog:
    """Older releases lack these optional tables and retain base portraits."""
    tables = set(
        session.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('pet_form_resource', 'pet_form_member')"
            )
        ).scalars()
    )
    resources = (
        {
            (int(pet), int(skin), int(index)): int(resource)
            for pet, skin, index, resource in session.execute(
                text(
                    "SELECT pet_id, skin_id, form_index, resource_id "
                    "FROM pet_form_resource WHERE resource_id > 0 AND form_index > 0"
                )
            )
        }
        if "pet_form_resource" in tables
        else {}
    )
    members = (
        frozenset(
            (int(canonical), int(pet))
            for canonical, pet in session.execute(
                text("SELECT canonical_pet_id, pet_id FROM pet_form_member")
            )
        )
        if "pet_form_member" in tables
        else frozenset()
    )
    return PetFormCatalog(resources, members)
