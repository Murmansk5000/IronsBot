# SPDX-License-Identifier: MIT
"""Resolve optional lineup slots from published Seer data."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ironsbot.extensions.contracts import (
    PlayerLineupPetSnapshot,
    PlayerLineupSlot,
)
from ironsbot.integrations.seer_data.skin_image_resolution import (
    load_skin_image_resolutions,
)
from ironsbot.services.seer.peak import (
    active_peak_pool_limits,
    load_peak_pools,
    snapshot_peak_pools,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess

logger = logging.getLogger(__name__)


class PublishedPlayerLineupEntryResolver:
    """Enrich private lineup slots without exposing ORM records to extensions."""

    def __init__(
        self,
        data: SeerDataAccess,
    ) -> None:
        self._data = data

    def resolve(
        self,
        slots: tuple[PlayerLineupSlot, ...],
    ) -> tuple[PlayerLineupPetSnapshot, ...]:
        pet_ids = {slot.pet_id for slot in slots}
        skin_ids = {slot.skin_id for slot in slots if slot.skin_id > 0}
        with self._data.query(
            lambda session: load_peak_pools(session, expert=False)
        ) as pools:
            peak_pool_limits = active_peak_pool_limits(snapshot_peak_pools(pools))
        with (
            self._data.query(
                lambda session: load_skin_image_resolutions(session, skin_ids)
            ) as resolved_skin_images,
            self._data.get_many(self._data.pet, pet_ids) as pets_by_id,
            self._data.get_many(self._data.pet_skin, skin_ids) as skins_by_id,
        ):
            return tuple(
                PlayerLineupPetSnapshot(
                    pet_id=slot.pet_id,
                    level=slot.level,
                    use_flag=slot.use_flag,
                    name=_pet_name(pets_by_id.get(slot.pet_id)),
                    resource_id=_resource_id(
                        slot,
                        pets_by_id.get(slot.pet_id),
                        skins_by_id.get(slot.skin_id),
                        resolved_skin_images.get(slot.skin_id),
                    ),
                    type_id=_type_id(pets_by_id.get(slot.pet_id)),
                    peak_pool_limit=peak_pool_limits.get(slot.pet_id),
                )
                for slot in slots
            )


def _pet_name(pet: object | None) -> str:
    return str(getattr(pet, "name", "")).strip() or "未知精灵"


def _resource_id(
    slot: PlayerLineupSlot,
    pet: object | None,
    skin: object | None,
    resolution: object | None,
) -> int:
    base_resource_id = int(getattr(pet, "resource_id", 0) or slot.pet_id)
    if slot.skin_id <= 0:
        return base_resource_id
    if skin is None:
        _log_unresolved_skin(slot, "skin not found")
        return 0
    skin_pet_id = int(getattr(skin, "pet_id", 0) or 0)
    if skin_pet_id > 0 and skin_pet_id != slot.pet_id:
        _log_unresolved_skin(slot, f"skin owner mismatch: {skin_pet_id}")
        return 0
    skin_resource_id = int(getattr(skin, "resource_id", 0) or 0)
    if skin_resource_id <= 0:
        _log_unresolved_skin(slot, "skin has no resource")
        return 0
    resolved_head_resource_id = int(getattr(resolution, "head_resource_id", 0) or 0)
    return resolved_head_resource_id or skin_resource_id


def _log_unresolved_skin(slot: PlayerLineupSlot, reason: str) -> None:
    logger.warning(
        "lineup skin portrait unresolved: pet_id=%s skin_id=%s reason=%s",
        slot.pet_id,
        slot.skin_id,
        reason,
    )


def _type_id(pet: object | None) -> int:
    return int(getattr(getattr(pet, "type", None), "id", 0) or 0)
