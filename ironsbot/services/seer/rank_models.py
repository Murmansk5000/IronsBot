# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RankLookupResult:
    title: str
    score_name: str
    rank: int | None = None
    score: int | None = None
    searched_limit: int = 0
    queried: bool = False


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
    fetched_at: float = 0.0
    items: list[RankScoreSearchItem] = field(default_factory=list)
    higher_gap: RankScoreGap | None = None
    lower_gap: RankScoreGap | None = None


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


@dataclass(slots=True)
class RankSummaryProgress:
    current_title: str = ""


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
        return cls(
            book=RankLookupResult(title="图鉴积分", score_name="图鉴积分"),
            achieve=RankLookupResult(title="成就点数", score_name="成就点数"),
            breakdown=BookBreakdownSummary.empty(),
        )


@dataclass(slots=True)
class PeakSeasonRankSummary:
    standard: RankLookupResult
    wild: RankLookupResult
    expert: RankLookupResult
    errors: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "PeakSeasonRankSummary":
        return cls(
            standard=RankLookupResult(title="竞技赛季榜", score_name="段位分"),
            wild=RankLookupResult(title="狂野赛季榜", score_name="段位分"),
            expert=RankLookupResult(title="专家赛季榜", score_name="专家积分"),
        )


__all__ = [
    "BookBreakdownSummary",
    "PeakSeasonRankSummary",
    "PlayerRankSummary",
    "RankLookupResult",
    "RankPageResult",
    "RankScoreGap",
    "RankScoreMissProof",
    "RankScoreSearchItem",
    "RankScoreSearchResult",
    "RankSummaryProgress",
]
