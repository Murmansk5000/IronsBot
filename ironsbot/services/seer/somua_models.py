# SPDX-License-Identifier: MIT
"""Verified extra fields on the public Somua leaderboard wire record."""

from __future__ import annotations

from dataclasses import dataclass

from ironsbot.services.seer.rank_models import RankEntry


@dataclass(frozen=True, slots=True)
class SomuaParts:
    body: int
    face: int
    hands: int
    ears: int
    tail: int
    head: int
    topwear: int
    back: int
    surround: int


@dataclass(frozen=True, slots=True)
class SomuaCommonSlot:
    sequence: int
    parts: SomuaParts


@dataclass(frozen=True, slots=True)
class SomuaRankEntry(RankEntry):
    common_somua: tuple[SomuaCommonSlot, ...]
