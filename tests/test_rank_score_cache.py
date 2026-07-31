from dataclasses import dataclass
from typing import Any

from ironsbot.services.seer.rank_score_cache import cached_score_candidate_page_starts
from ironsbot.services.seer.rank_score_helpers import score_segment_sample_indexes


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


def _rank_page_start(index: int) -> int:
    return index // 10 * 10


def test_score_segment_sample_indexes_uses_equal_head_and_tail_halves() -> None:
    assert score_segment_sample_indexes(100, 200, 9) == {
        100,
        101,
        102,
        103,
        196,
        197,
        198,
        199,
    }
    assert score_segment_sample_indexes(100, 109, 9) is None
    assert score_segment_sample_indexes(100, 110, 9) == {
        100,
        101,
        102,
        103,
        106,
        107,
        108,
        109,
    }


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
