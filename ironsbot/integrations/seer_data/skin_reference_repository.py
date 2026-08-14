# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve published skin resource identifiers into detached records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from seerapi_models import PetSkinORM
from sqlmodel import col, select

if TYPE_CHECKING:
    from sqlmodel import Session


@dataclass(frozen=True, slots=True)
class SkinReferenceRecord:
    skin_id: int
    resource_id: int
    name: str


def load_skins_by_resource_id(
    session: Session,
    *,
    references: frozenset[int],
) -> tuple[SkinReferenceRecord, ...]:
    if not references:
        return ()
    rows = session.exec(
        select(PetSkinORM).where(col(PetSkinORM.resource_id).in_(references))
    )
    return tuple(
        SkinReferenceRecord(int(row.id), int(row.resource_id), str(row.name))
        for row in rows
    )
