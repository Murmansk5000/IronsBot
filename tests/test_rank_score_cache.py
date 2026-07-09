from dataclasses import dataclass
from typing import Any

from ironsbot.services.seer.rank_score_cache import (
    cached_score_candidate_page_starts,
    cached_score_miss_boundary,
)
from ironsbot.services.seer.rank_score_helpers import score_miss_proof_from_page

FETCHED_AT = 1234.0
LOWER_SCORE = 99
HIGHER_SCORE = 101
HIGHER_START_RANK = 52
LOWER_START_RANK = 53


@dataclass(frozen=True)
class CacheSummary:
    start_index: int
    end_index: int
    min_score: int
    max_score: int
    item_count: int = 0
    expected_count: int = 0
    fetched_at: float = 0.0
    is_stale: bool = False
    is_partial: bool = False


@dataclass(frozen=True)
class RankItem:
    id: int
    nick: str
    score: int


@dataclass(frozen=True)
class CachedPageResult:
    fetched_at: float
    items: list[RankItem]


def _rank_page_start(index: int) -> int:
    return index // 10 * 10


def test_cached_score_candidate_page_starts_uses_facts_and_score_bounds() -> None:
    def get_cached_score_indexes(**_kwargs: Any) -> list[int]:
        return [57, 63]

    def get_cache_summary(**_kwargs: Any) -> list[CacheSummary]:
        return [
            CacheSummary(
                start_index=82,
                end_index=89,
                min_score=90,
                max_score=110,
            ),
            CacheSummary(
                start_index=120,
                end_index=129,
                min_score=90,
                max_score=110,
            ),
            CacheSummary(
                start_index=30,
                end_index=39,
                min_score=10,
                max_score=20,
            ),
        ]

    assert cached_score_candidate_page_starts(
        key=1,
        sub_key=0,
        target_score=100,
        start_index=50,
        end_index=100,
        rank_page_start=_rank_page_start,
        get_cached_score_indexes=get_cached_score_indexes,
        get_cache_summary=get_cache_summary,
    ) == [50, 60, 80]


def test_cached_score_miss_boundary_uses_complete_cached_page_gap() -> None:
    def get_cache_summary(**_kwargs: Any) -> list[CacheSummary]:
        return [
            CacheSummary(
                start_index=50,
                end_index=53,
                item_count=4,
                expected_count=4,
                min_score=90,
                max_score=110,
                fetched_at=FETCHED_AT,
                is_stale=False,
                is_partial=False,
            )
        ]

    def get_cached_score_indexes(**_kwargs: Any) -> list[int]:
        return []

    def get_cached_page_result(**_kwargs: Any) -> CachedPageResult:
        return CachedPageResult(
            fetched_at=FETCHED_AT,
            items=[
                RankItem(id=1, nick="A", score=110),
                RankItem(id=2, nick="B", score=HIGHER_SCORE),
                RankItem(id=3, nick="C", score=LOWER_SCORE),
                RankItem(id=4, nick="D", score=90),
            ],
        )

    proof = cached_score_miss_boundary(
        key=1,
        sub_key=0,
        target_score=100,
        start_index=0,
        end_index=100,
        rank_offset=0,
        get_cache_summary=get_cache_summary,
        get_cached_score_indexes=get_cached_score_indexes,
        get_cached_page_result=get_cached_page_result,
        score_miss_proof_from_page=score_miss_proof_from_page,
    )

    assert proof is not None
    assert proof.boundary_score == LOWER_SCORE
    assert proof.fetched_at == FETCHED_AT
    assert proof.higher_gap is not None
    assert proof.higher_gap.score == HIGHER_SCORE
    assert proof.higher_gap.start_rank == HIGHER_START_RANK
    assert proof.lower_gap is not None
    assert proof.lower_gap.score == LOWER_SCORE
    assert proof.lower_gap.start_rank == LOWER_START_RANK
