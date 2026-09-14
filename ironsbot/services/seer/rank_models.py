# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class RankEntry:
    id: int
    nick: str
    score: int


@dataclass(slots=True)
class RankLookupCost:
    """Observed work for one player-rank lookup."""

    anchor_page_start: int | None = None
    page_starts: list[int] = field(default_factory=list)
    anchor_page_hit: bool = False
    expanded: bool = False
    used_score_search: bool = False
    used_full_scan: bool = False
    cache_page_hits: int = 0
    online_page_fetches: int = 0
    restricted_miss: bool = False
    cached_rank_age_seconds: float | None = None
    used_recent_cache_anchor: bool = False
    used_recent_cache_fallback: bool = False

    @property
    def lightweight_confirmed(self) -> bool:
        return (
            self.anchor_page_start is not None
            and self.anchor_page_hit
            and self.page_starts == [self.anchor_page_start]
            and not self.used_score_search
            and not self.used_full_scan
        )


@dataclass(slots=True)
class RankLookupResult:
    title: str
    score_name: str
    rank: int | None = None
    score: int | None = None
    observed_score: int | None = None
    excluded: bool = False
    searched_limit: int = 0
    queried: bool = False
    failure: str | None = None
    fallback_cached_at: float | None = None
    fetched_at: float | None = None
    profile_score: int | None = None
    scanned_count: int = 0
    scan_complete: bool = False
    budget_exhausted: bool = False
    query_id: str = "-"
    cost: RankLookupCost = field(default_factory=RankLookupCost)

    @property
    def status(self) -> str:
        if self.failure and "顺序异常" in self.failure:
            return "order_anomaly"
        if self.budget_exhausted and self.rank is None:
            return "budget_exhausted"
        if self.failure:
            return "failed"
        if self.rank is not None:
            return "found"
        if self.scan_complete:
            return "scanned_missing"
        return "unconfirmed" if self.queried else "not_queried"

    def record_page(self, start: int, page: RankPageResult) -> None:
        """Retain the oldest page evidence and its observed query cost."""
        self.include_observation(page.fetched_at)
        self.queried = True
        self.cost.page_starts.append(start)
        if page.from_cache:
            self.cost.cache_page_hits += 1
        else:
            self.cost.online_page_fetches += 1

    def include_observation(self, fetched_at: float) -> None:
        self.fetched_at = (
            fetched_at
            if self.fetched_at is None
            else min(self.fetched_at, fetched_at)
        )


@dataclass(slots=True)
class RankScoreSearchItem:
    id: int
    nick: str
    score: int
    rank_index: int


@dataclass(slots=True)
class RankScoreGap:
    score: int
    start_rank: int
    end_rank: int
    total_count: int
    truncated: bool = False
    items: list[RankScoreSearchItem] = field(default_factory=list)


@dataclass(slots=True)
class RankScoreSearchResult:
    title: str
    score_name: str
    target_score: int
    searched_limit: int = 0
    queried: bool = False
    boundary_score: int | None = None
    start_rank: int | None = None
    end_rank: int | None = None
    total_count: int = 0
    scanned_count: int = 0
    truncated: bool = False
    budget_exhausted: bool = False
    fetched_at: float | None = None
    items: list[RankScoreSearchItem] = field(default_factory=list)
    higher_gap: RankScoreGap | None = None
    lower_gap: RankScoreGap | None = None
    failure: str | None = None


@dataclass(slots=True)
class RankScoreMissProof:
    boundary_score: int
    fetched_at: float
    higher_gap: RankScoreGap | None = None
    lower_gap: RankScoreGap | None = None


@dataclass(slots=True)
class RankPageResult:
    items: list[Any]
    fetched_at: float
    from_cache: bool = False


@dataclass(slots=True)
class RankRangeResult:
    """A composed window; no page read means no observation timestamp."""

    items: list[Any]
    fetched_at: float | None
    from_cache: bool = False


@dataclass(slots=True)
class RankSummaryProgress:
    current_title: str = ""
    completed: dict[str, RankLookupResult] = field(default_factory=dict)


@dataclass(slots=True)
class BookBreakdownSummary:
    pet_kind_count: int = 0
    pet_kind: RankLookupResult | None = None
    skin: RankLookupResult | None = None
    countermark: RankLookupResult | None = None
    outfit_suit: RankLookupResult | None = None
    outfit_part: RankLookupResult | None = None
    mount: RankLookupResult | None = None

    @classmethod
    def empty(cls) -> "BookBreakdownSummary":
        return cls(
            pet_kind=RankLookupResult(title="精灵图鉴", score_name="精灵"),
            skin=RankLookupResult(title="皮肤图鉴", score_name="皮肤"),
            countermark=RankLookupResult(title="刻印图鉴", score_name="刻印"),
            outfit_suit=RankLookupResult(title="套装图鉴", score_name="套装"),
            outfit_part=RankLookupResult(title="部件图鉴", score_name="部件"),
            mount=RankLookupResult(title="座驾图鉴", score_name="座驾"),
        )

    @property
    def outfit_count(self) -> int | None:
        suit_score = None if self.outfit_suit is None else self.outfit_suit.score
        part_score = None if self.outfit_part is None else self.outfit_part.score
        if suit_score is None or part_score is None:
            return None
        return int(suit_score) + int(part_score)

    @property
    def unlocked_count(self) -> int | None:
        scores: tuple[int | None, ...] = (
            self.pet_kind_count,
            None if self.skin is None else self.skin.score,
            None if self.countermark is None else self.countermark.score,
            self.outfit_count,
            None if self.mount is None else self.mount.score,
        )
        present_scores = [score for score in scores if score is not None]
        if len(present_scores) != len(scores):
            return None
        return sum(present_scores)


@dataclass(slots=True)
class PlayerRankSummary:
    book: RankLookupResult
    achieve: RankLookupResult
    breakdown: BookBreakdownSummary
    errors: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "PlayerRankSummary":
        return cls.from_results({})

    @classmethod
    def from_results(
        cls,
        results: Mapping[str, RankLookupResult],
        *,
        pet_kind_count: int = 0,
        errors: tuple[str, ...] = (),
        failure: str | None = None,
    ) -> "PlayerRankSummary":
        def item(key: str, title: str, score_name: str) -> RankLookupResult:
            return results.get(key) or RankLookupResult(
                title=title,
                score_name=score_name,
                failure=failure,
            )

        return cls(
            book=item("book", "图鉴积分", "图鉴积分"),
            achieve=item("achieve", "成就点数", "成就点数"),
            breakdown=BookBreakdownSummary(
                pet_kind_count=pet_kind_count,
                pet_kind=item("pet_kind", "精灵图鉴", "精灵"),
                skin=item("skin", "皮肤图鉴", "皮肤"),
                countermark=item("countermark", "刻印图鉴", "刻印"),
                outfit_suit=item("outfit_suit", "套装图鉴", "套装"),
                outfit_part=item("outfit_part", "部件图鉴", "部件"),
                mount=item("mount", "座驾图鉴", "座驾"),
            ),
            errors=errors,
        )


@dataclass(slots=True)
class PeakSeasonRankSummary:
    standard: RankLookupResult
    wild: RankLookupResult
    expert: RankLookupResult

    @classmethod
    def empty(cls) -> "PeakSeasonRankSummary":
        return cls.from_results({})

    @classmethod
    def from_results(
        cls,
        results: Mapping[str, RankLookupResult],
        *,
        failure: str | None = None,
    ) -> "PeakSeasonRankSummary":
        def item(key: str, title: str, score_name: str) -> RankLookupResult:
            return results.get(key) or RankLookupResult(
                title=title,
                score_name=score_name,
                failure=failure,
            )

        return cls(
            standard=item("standard_peak", "竞技赛季榜", "段位分"),
            wild=item("wild_peak", "狂野赛季榜", "段位分"),
            expert=item("expert_peak", "专家赛季榜", "专家积分"),
        )
