# SPDX-License-Identifier: MIT
"""Published detail facts exposed through the public lineup contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from seerapi_models import MintmarkORM, PetEffectORM, SkillORM
from seerapi_models.common import EidEffectInUseORM
from sqlalchemy.orm import selectinload
from sqlmodel import col, select

from ironsbot.extensions.contracts import (
    PlayerLineupDetailCatalog,
    PlayerLineupTraitSnapshot,
)

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataReader


class PublishedPlayerLineupDetailResolver:
    def __init__(self, data: SeerDataReader) -> None:
        self._data = data

    def resolve(
        self,
        *,
        skill_ids: tuple[int, ...],
        mintmark_ids: tuple[int, ...],
        effect_ids: tuple[int, ...],
    ) -> PlayerLineupDetailCatalog:
        with self._data.query(
            lambda session: _load_details(session, skill_ids, mintmark_ids, effect_ids)
        ) as catalog:
            return catalog


def _load_details(
    session: Session,
    skill_ids: tuple[int, ...],
    mintmark_ids: tuple[int, ...],
    effect_ids: tuple[int, ...],
) -> PlayerLineupDetailCatalog:
    skills = (
        tuple(
            (int(skill.id), str(skill.name or "").strip())
            for skill in session.exec(
                select(SkillORM).where(col(SkillORM.id).in_(skill_ids))
            )
        )
        if skill_ids
        else ()
    )
    mintmarks = (
        tuple(
            (int(mark.id), str(mark.name or "").strip())
            for mark in session.exec(
                select(MintmarkORM).where(col(MintmarkORM.id).in_(mintmark_ids))
            )
        )
        if mintmark_ids
        else ()
    )
    traits = ()
    if effect_ids:
        statement = (
            select(PetEffectORM)
            .join(
                EidEffectInUseORM,
                col(PetEffectORM.effect_in_use_id) == EidEffectInUseORM.id,
            )
            .where(col(EidEffectInUseORM.eid).in_(effect_ids))
            .options(selectinload(cast("Any", PetEffectORM.effect_in_use)))
        )
        traits = tuple(
            PlayerLineupTraitSnapshot(
                effect_id=int(trait.effect_in_use.eid),
                args=tuple(int(arg) for arg in trait.effect_in_use.effect_args or ()),
                name=str(trait.name or "").strip(),
                description=str(trait.desc or "").strip(),
                star_level=int(trait.star_level),
            )
            for trait in session.exec(statement)
            if trait.effect_in_use is not None
        )
    return PlayerLineupDetailCatalog(skills, mintmarks, traits)
