# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class LocalRankSummary:
    text: str = ""
    sample_ranks: dict[str, str] = field(default_factory=dict)

    def sample_rank(self, metric_key: str) -> str:
        return self.sample_ranks.get(metric_key, "")


@dataclass(frozen=True, slots=True)
class LocalRankEntry:
    rank: int
    user_id: int
    nick: str
    value: int
    display: str


@dataclass(frozen=True, slots=True)
class LocalRankCacheStats:
    player_count: int
    total_player_count: int
    max_players: int
    metric_counts: dict[str, int]
