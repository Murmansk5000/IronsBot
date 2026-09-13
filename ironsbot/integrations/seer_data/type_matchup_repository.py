# SPDX-License-Identifier: GPL-3.0-or-later
"""Read detached element-type facts for the type-matchup domain."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from seerapi_models import ElementTypeORM
from seerapi_models.element_type import ElementTypeRelationORM, TypeCombinationORM
from sqlmodel import col, select

from ironsbot.services.seer.data import SEERAPI_DB
from ironsbot.services.seer.type_calc import (
    ElementTypeSnapshot,
    TypeCombinationSnapshot,
    TypeMatchupDataset,
)

from .getters import TypeCombinationDataGetter

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataReader


class PublishedTypeMatchupRepository:
    def __init__(self, data: SeerDataReader) -> None:
        self._data = data

    def resolve(self, arg: str) -> tuple[TypeCombinationSnapshot, ...]:
        with self._data.query(
            partial(resolve_type_combinations, arg=arg)
        ) as combinations:
            return combinations

    def load_dataset(self) -> TypeMatchupDataset:
        with self._data.query(load_type_matchup_dataset) as dataset:
            return dataset


def load_type_matchup_dataset(session: Session) -> TypeMatchupDataset:
    """Load every official type and relation required by the pure calculator."""

    combinations = tuple(
        _combination_snapshot(item)
        for item in session.exec(
            select(TypeCombinationORM).order_by(col(TypeCombinationORM.id))
        )
    )
    elements = tuple(
        ElementTypeSnapshot(id=int(item.id), name=str(item.name))
        for item in session.exec(
            select(ElementTypeORM).order_by(col(ElementTypeORM.id))
        )
    )
    relations = tuple(
        (int(source_id), int(target_id), float(multiplier))
        for source_id, target_id, multiplier in session.exec(
            select(
                ElementTypeRelationORM.source_id,
                ElementTypeRelationORM.target_id,
                ElementTypeRelationORM.multiple,
            ).order_by(
                col(ElementTypeRelationORM.source_id),
                col(ElementTypeRelationORM.target_id),
            )
        )
    )
    return TypeMatchupDataset(
        combinations=combinations,
        elements=elements,
        relations=relations,
    )


def _combination_snapshot(item: TypeCombinationORM) -> TypeCombinationSnapshot:
    return TypeCombinationSnapshot(
        id=int(item.id),
        name=str(item.name),
        primary_id=int(item.primary_id),
        secondary_id=None if item.secondary_id is None else int(item.secondary_id),
    )


def resolve_type_combinations(
    session: Session, arg: str
) -> tuple[TypeCombinationSnapshot, ...]:
    return tuple(
        _combination_snapshot(item)
        for item in TypeCombinationDataGetter({SEERAPI_DB: session}, arg)
    )
