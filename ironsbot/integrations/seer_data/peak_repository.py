# SPDX-License-Identifier: GPL-3.0-or-later
"""Read detached official peak-pool facts for Seer services and renderers."""

from __future__ import annotations

from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, cast

from seerapi_models import (
    PeakExpertPoolORM,
    PeakPoolORM,
    PeakPoolVoteORM,
    PeakSeasonORM,
    PetORM,
)
from sqlalchemy import text
from sqlalchemy.orm import selectinload
from sqlmodel import col, select

from ironsbot.services.seer.peak import PeakPeriodTimes

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataAccess, SeerDataReader
    from ironsbot.services.seer.peak import (
        PeakPetSnapshot,
        PeakPoolSnapshot,
        PeakVoteSnapshot,
    )


class PublishedPeakRepository:
    def __init__(self, data: SeerDataReader) -> None:
        self._data = data

    def pools(self, *, expert: bool) -> tuple[PeakPoolSnapshot, ...]:
        with self._data.query(
            partial(load_peak_pool_snapshots, expert=expert)
        ) as pools:
            return pools

    def master_pools(self) -> tuple[PeakPoolSnapshot, ...]:
        with self._data.query(load_peak_master_pool_snapshots) as pools:
            return pools

    def votes(self) -> tuple[PeakVoteSnapshot, ...]:
        with self._data.query(load_peak_vote_snapshots) as votes:
            return votes

    def period(self, *, monthly: bool) -> PeakPeriodTimes | None:
        with self._data.query(
            partial(load_peak_period_times, monthly=monthly)
        ) as period:
            return period

    def pets(self, pet_ids: set[int]) -> dict[int, PeakPetSnapshot]:
        with self._data.query(
            partial(load_peak_pet_snapshots, pet_ids=pet_ids)
        ) as pets:
            return pets

    def item_names(
        self,
        kind: Literal["suit", "title"],
        item_ids: set[int],
    ) -> dict[int, str]:
        data = cast("SeerDataAccess", self._data)
        getter = data.suit if kind == "suit" else data.title
        with data.get_many(getter, item_ids) as models:
            return {item_id: str(model.name) for item_id, model in models.items()}


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
        for pool in session.exec(
            select(model).options(selectinload(cast("Any", model.pet)))
        )
    )


def load_peak_master_pool_snapshots(
    session: Session,
) -> tuple[PeakPoolSnapshot, ...]:
    """Read the producer-owned master-pool relation without duplicating its model."""

    from ironsbot.services.seer.peak import PeakPetSnapshot, PeakPoolSnapshot

    rows = session.execute(
        text(
            "SELECT pool.id, pool.cost, pool.start_time, pool.end_time, "
            "pet.id AS pet_id, pet.name AS pet_name, "
            "pet.resource_id, pet.type_id "
            "FROM peak_cost_pool AS pool "
            "LEFT JOIN pet ON pet.peak_cost_pool_id = pool.id "
            "ORDER BY pool.cost DESC, pool.id, pet.id"
        )
    ).mappings()
    grouped: dict[int, tuple[int, datetime, datetime, list[PeakPetSnapshot]]] = {}
    for row in rows:
        pool_id = int(row["id"])
        if pool_id not in grouped:
            grouped[pool_id] = (
                int(row["cost"]),
                _as_datetime(row["start_time"]),
                _as_datetime(row["end_time"]),
                [],
            )
        if row["pet_id"] is not None:
            grouped[pool_id][3].append(
                PeakPetSnapshot(
                    id=int(row["pet_id"]),
                    name=str(row["pet_name"]),
                    resource_id=int(row["resource_id"] or row["pet_id"]),
                    type_id=int(row["type_id"] or 0),
                )
            )
    return tuple(
        PeakPoolSnapshot(pool_id, cost, start_time, end_time, tuple(pets))
        for pool_id, (cost, start_time, end_time, pets) in grouped.items()
    )


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


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
        for vote in session.exec(
            select(PeakPoolVoteORM).options(
                selectinload(cast("Any", PeakPoolVoteORM.pet))
            )
        )
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


def _peak_pet_snapshot(pet: PetORM) -> PeakPetSnapshot:
    from ironsbot.services.seer.peak import PeakPetSnapshot

    return PeakPetSnapshot(
        id=int(pet.id),
        name=str(pet.name),
        resource_id=int(pet.resource_id),
        type_id=int(pet.type_id),
    )
