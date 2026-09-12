# SPDX-License-Identifier: GPL-3.0-or-later
"""Read detached official peak-pool facts for Seer services and renderers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from seerapi_models import (
    PeakExpertPoolORM,
    PeakPoolORM,
    PeakPoolVoteORM,
    PeakSeasonORM,
    PetORM,
)
from sqlmodel import col, select

if TYPE_CHECKING:
    from datetime import datetime

    from sqlmodel import Session

    from ironsbot.services.seer.peak import (
        PeakPetSnapshot,
        PeakPoolSnapshot,
        PeakVoteSnapshot,
    )


@dataclass(frozen=True, slots=True)
class PeakPeriodTimes:
    start_time: datetime
    end_time: datetime


def load_peak_pool_snapshots(
    session: Session,
    *,
    expert: bool,
) -> tuple[PeakPoolSnapshot, ...]:
    model = PeakExpertPoolORM if expert else PeakPoolORM
    from ironsbot.services.seer.peak import PeakPoolSnapshot

    return tuple(
        PeakPoolSnapshot(
            id=int(pool.id),
            count=int(pool.count),
            start_time=pool.start_time,
            end_time=pool.end_time,
            pets=tuple(_peak_pet_snapshot(pet) for pet in pool.pet),
        )
        for pool in session.exec(select(model))
    )


def load_peak_vote_snapshots(session: Session) -> tuple[PeakVoteSnapshot, ...]:
    from ironsbot.services.seer.peak import PeakVoteSnapshot

    return tuple(
        PeakVoteSnapshot(
            id=int(vote.id),
            count=int(vote.count),
            subkey=int(vote.subkey),
            start_time=vote.start_time,
            end_time=vote.end_time,
            pets=tuple(_peak_pet_snapshot(pet) for pet in vote.pet),
        )
        for vote in session.exec(select(PeakPoolVoteORM))
    )


def load_peak_period_times(
    session: Session,
    *,
    monthly: bool,
) -> PeakPeriodTimes | None:
    if monthly:
        pool = session.exec(select(PeakExpertPoolORM)).first()
        return None if pool is None else PeakPeriodTimes(pool.start_time, pool.end_time)
    season = session.get(PeakSeasonORM, 1)
    if season is None:
        return None
    return PeakPeriodTimes(season.start_time, season.end_time)


def load_peak_pet_snapshots(
    session: Session, pet_ids: set[int]
) -> dict[int, PeakPetSnapshot]:
    """Read and detach only the pets requested by the online ranking."""
    if not pet_ids:
        return {}
    return {
        int(pet.id): _peak_pet_snapshot(pet)
        for pet in session.exec(select(PetORM).where(col(PetORM.id).in_(pet_ids)))
    }


def _peak_pet_snapshot(pet: Any) -> PeakPetSnapshot:
    from ironsbot.services.seer.peak import PeakPetSnapshot

    return PeakPetSnapshot(
        id=int(pet.id),
        name=str(pet.name),
        resource_id=int(pet.resource_id),
        type_id=int(pet.type.id),
    )
