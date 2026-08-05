# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.services.seer.rank_list_models import GlobalRankSpec


@dataclass(frozen=True, slots=True)
class RankPageRefreshTarget:
    rank_key: str
    spec: GlobalRankSpec
    reason: str
    start_rank: int
    end_rank: int
    raw_start: int
    raw_end: int


@dataclass(frozen=True, slots=True)
class RankPageRefreshFailure:
    target: RankPageRefreshTarget
    reason: str


@dataclass(slots=True)
class RankPageRefreshResult:
    targets: list[RankPageRefreshTarget]
    parallelism: int = 1
    refreshed: list[RankPageRefreshTarget] = field(default_factory=list)
    failures: list[RankPageRefreshFailure] = field(default_factory=list)
    worker_page_counts: dict[int, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.targets)

    @property
    def success(self) -> int:
        return len(self.refreshed)

    @property
    def failed(self) -> int:
        return len(self.failures)
