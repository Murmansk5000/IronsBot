# SPDX-License-Identifier: MIT
"""Verified extra fields on the public Somua leaderboard wire record."""

from __future__ import annotations

from dataclasses import dataclass

from ironsbot.services.seer.query_result import QueryReply
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


@dataclass(frozen=True, slots=True)
class SomuaParent:
    name: str
    generation: int
    parts: SomuaParts
    owner_name: str
    created_at: int


@dataclass(frozen=True, slots=True)
class SomuaDetail:
    sequence: int
    name: str
    generation: int
    form_id: int
    stage: int
    created_at: int
    last_touch_at: int
    location: int
    genes: tuple[int, ...]
    match_flag: int
    attack_mode: int
    personality: int
    attributes: tuple[int, ...]
    parts: SomuaParts
    father: SomuaParent
    mother: SomuaParent
    achievement_id: int
    is_collected: int
    player_id: int


@dataclass(frozen=True, slots=True)
class SomuaOverviewReply(QueryReply):
    common_somua: tuple[SomuaCommonSlot, ...] | None = None
    common_fetched_at: float | None = None
    common_names: tuple[tuple[int, str], ...] = ()
