# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.services.seer.pet_partner import PetPartner

    from .custom_pet_models import SoulmarkDict

PARTNER_UPGRADE_MIN_SIMILARITY = 0.8


def partition_soulmarks(
    soulmarks: list[SoulmarkDict],
    partner: PetPartner | None,
) -> tuple[list[SoulmarkDict], list[SoulmarkDict]]:
    upgraded_indexes = {
        index for index, soulmark in enumerate(soulmarks) if soulmark["intensified"]
    }
    if partner is not None:
        partner_upgrade_index = _find_partner_upgrade_soulmark_index(
            soulmarks,
            partner,
        )
        if partner_upgrade_index is not None:
            upgraded_indexes.add(partner_upgrade_index)

    return (
        [
            soulmark
            for index, soulmark in enumerate(soulmarks)
            if index not in upgraded_indexes
        ],
        [
            soulmark
            for index, soulmark in enumerate(soulmarks)
            if index in upgraded_indexes
        ],
    )


def _find_partner_upgrade_soulmark_index(
    soulmarks: Sequence[SoulmarkDict],
    partner: PetPartner,
) -> int | None:
    """Locate the real upgraded soulmark instead of rendering partner text again."""
    indexes_by_id = {soulmark["id"]: index for index, soulmark in enumerate(soulmarks)}
    for soulmark in soulmarks:
        upgraded_id = soulmark["intensified_to_id"]
        if upgraded_id is not None and upgraded_id in indexes_by_id:
            return indexes_by_id[upgraded_id]

    after = _normalize_soulmark_text(partner.after_description)
    before = _normalize_soulmark_text(partner.before_description)
    if not after:
        return None

    contained_index = _contained_partner_upgrade_index(soulmarks, after, before)
    if contained_index is not None:
        return contained_index
    return _similar_partner_upgrade_index(soulmarks, after, before)


def _contained_partner_upgrade_index(
    soulmarks: Sequence[SoulmarkDict],
    after: str,
    before: str,
) -> int | None:
    after_indexes = _contained_soulmark_indexes(soulmarks, after)
    before_indexes = _contained_soulmark_indexes(soulmarks, before)
    if not after_indexes:
        return None
    after_index = max(after_indexes, key=lambda index: soulmarks[index]["id"])
    if not before_indexes:
        return after_index
    before_index = max(before_indexes, key=lambda index: soulmarks[index]["id"])
    if soulmarks[before_index]["id"] > soulmarks[after_index]["id"]:
        return before_index
    return after_index


def _similar_partner_upgrade_index(
    soulmarks: Sequence[SoulmarkDict],
    after: str,
    before: str,
) -> int | None:
    candidates = [
        (
            SequenceMatcher(
                None, _normalize_soulmark_text(soulmark["desc"]), after
            ).ratio(),
            SequenceMatcher(
                None,
                _normalize_soulmark_text(soulmark["desc"]),
                before,
            ).ratio(),
            index,
        )
        for index, soulmark in enumerate(soulmarks)
    ]
    if not candidates:
        return None
    after_score, _before_score, after_index = max(
        candidates,
        key=lambda candidate: (candidate[0] - candidate[1], candidate[0]),
    )
    if after_score < PARTNER_UPGRADE_MIN_SIMILARITY:
        return None

    _after_score, before_score, before_index = max(
        candidates,
        key=lambda candidate: (candidate[1] - candidate[0], candidate[1]),
    )
    if (
        before_score >= PARTNER_UPGRADE_MIN_SIMILARITY
        and before_index != after_index
        and soulmarks[before_index]["id"] > soulmarks[after_index]["id"]
    ):
        return before_index
    return after_index


def _contained_soulmark_indexes(
    soulmarks: Sequence[SoulmarkDict],
    partner_description: str,
) -> list[int]:
    if not partner_description:
        return []
    return [
        index
        for index, soulmark in enumerate(soulmarks)
        if (description := _normalize_soulmark_text(soulmark["desc"]))
        and (description in partner_description or partner_description in description)
    ]


def _normalize_soulmark_text(value: str | None) -> str:
    without_markup = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"[\W_]+", "", without_markup).casefold()
