# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve partner-driven soulmark display facts before presentation."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.services.seer.rendering.pet_info_models import (
        PetPartnerSnapshot,
        PetSoulmarkSnapshot,
    )

_PARTNER_UPGRADE_MIN_SIMILARITY = 0.8


def resolve_partner_upgraded_soulmark_ids(
    soulmarks: Sequence[PetSoulmarkSnapshot],
    partner: PetPartnerSnapshot | None,
) -> frozenset[int]:
    """Return raw soulmark IDs the partner record identifies as upgraded.

    The published soulmark relation is authoritative when present. Older data
    can only describe the before/after texts, so the repository uses the
    existing bounded text comparison once while creating the detached snapshot.
    Presenters receive this resolved fact and never repeat the inference.
    """
    if partner is None or not soulmarks:
        return frozenset()

    soulmark_ids = {soulmark.id for soulmark in soulmarks}
    linked_ids = {
        soulmark.intensified_to_id
        for soulmark in soulmarks
        if soulmark.intensified_to_id in soulmark_ids
    }
    if linked_ids:
        return frozenset(linked_ids)

    after = _normalize_text(partner.after_description)
    before = _normalize_text(partner.before_description)
    if not after:
        return frozenset()
    candidates = [
        (
            SequenceMatcher(None, _normalize_soulmark(soulmark), after).ratio(),
            SequenceMatcher(None, _normalize_soulmark(soulmark), before).ratio(),
            soulmark.id,
        )
        for soulmark in soulmarks
    ]
    after_score, _before_score, after_id = max(
        candidates,
        key=lambda value: (value[0] - value[1], value[0]),
    )
    if after_score < _PARTNER_UPGRADE_MIN_SIMILARITY:
        return frozenset()
    _after_score, before_score, before_id = max(
        candidates,
        key=lambda value: (value[1] - value[0], value[1]),
    )
    if (
        before_score >= _PARTNER_UPGRADE_MIN_SIMILARITY
        and before_id != after_id
        and before_id > after_id
    ):
        return frozenset((before_id,))
    return frozenset((after_id,))


def _normalize_soulmark(soulmark: PetSoulmarkSnapshot) -> str:
    return _normalize_text(
        soulmark.analyze_desc or soulmark.formatting_adjustment or soulmark.desc
    )


def _normalize_text(value: str | None) -> str:
    return re.sub(r"[\W_]+", "", re.sub(r"<[^>]+>", "", value or "")).casefold()
