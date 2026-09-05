# SPDX-License-Identifier: MIT
"""Read the official competitive-point groups from the published database."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.core import time
from ironsbot.services.seer.peak import PeakPetSnapshot, PeakPoolSnapshot

if TYPE_CHECKING:
    from sqlmodel import Session


class MasterPoolUnavailableError(RuntimeError):
    pass


def load_master_pools(session: Session) -> tuple[PeakPoolSnapshot, ...]:
    try:
        rows = (
            session.execute(
                text(
                    "SELECT id, cost, pet_ids_json, subkey_total FROM peak_master_pool "
                    "ORDER BY cost DESC, id"
                )
            )
            .mappings()
            .all()
        )
        pets = {
            int(row.id): PeakPetSnapshot(
                id=int(row.id),
                name=str(row.name),
                resource_id=int(row.resource_id or row.id),
                type_id=int(row.type_id),
            )
            for row in session.execute(
                text("SELECT id, name, resource_id, type_id FROM pet")
            )
        }
    except SQLAlchemyError as error:
        raise MasterPoolUnavailableError from error
    pools = []
    for row in rows:
        ids = json.loads(row["pet_ids_json"])
        period = datetime.strptime(str(row["subkey_total"]), "%Y%m%d").replace(
            tzinfo=time.TZ_CN,
        )
        pools.append(
            PeakPoolSnapshot(
                id=int(row["id"]),
                count=int(row["cost"]),
                start_time=period,
                end_time=period,
                pets=tuple(
                    pets.get(pet_id)
                    or PeakPetSnapshot(
                        id=pet_id,
                        name=str(pet_id),
                        resource_id=pet_id,
                        type_id=0,
                    )
                    for pet_id in ids
                ),
            )
        )
    return tuple(pools)
