# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CachedRankItem:
    id: int
    nick: str
    score: int


@dataclass(frozen=True, slots=True)
class CachedRankPage:
    items: list[CachedRankItem]
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


__all__ = [
    "CachedRankItem",
    "CachedRankLookup",
    "CachedRankPage",
    "CachedRankPageSummary",
]
