# SPDX-License-Identifier: MIT
"""Draw two distinct published pets inside one short-lived read session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerapi_models import PetORM
from sqlmodel import col, func, select

from ironsbot.integrations.seer_data.type_matchup_repository import (
    load_type_matchup_dataset,
)
from ironsbot.services.seer.pet_flip import FlipPet

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataReader
    from ironsbot.services.seer.type_calc import TypeMatchupDataset


class PublishedPetFlipRepository:
    def __init__(self, data: SeerDataReader) -> None:
        self._data = data

    def draw(self) -> tuple[tuple[FlipPet, ...], TypeMatchupDataset]:
        with self._data.query(_draw) as result:
            return result


def _draw(session: Session) -> tuple[tuple[FlipPet, ...], TypeMatchupDataset]:
    dataset = load_type_matchup_dataset(session)
    elements = {element.id: element for element in dataset.combinations}
    pets = session.exec(
        select(PetORM)
        .where(col(PetORM.type_id).in_(tuple(elements)))
        .order_by(func.random())
        .limit(2)
    ).all()
    return tuple(
        FlipPet(int(pet.id), str(pet.name), int(pet.resource_id), elements[pet.type_id])
        for pet in pets
    ), dataset
