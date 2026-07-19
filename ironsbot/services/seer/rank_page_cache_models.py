# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.services.seer.rank_models import RankEntry


@dataclass(frozen=True, slots=True)
class CachedRankPage:
    items: list[RankEntry]
    fetched_at: float


@dataclass(frozen=True, slots=True)
class CachedRankLookup:
    id: int
    nick: str
    score: int
    rank_index: int
    fetched_at: float
    is_stale: bool = False


@dataclass(frozen=True, slots=True)
class CachedRankPageSummary:
    start_index: int
    end_index: int
    item_count: int
    expected_count: int
    fetched_at: float
    min_score: int | None = None
    max_score: int | None = None
    is_stale: bool = False
    is_partial: bool = False
