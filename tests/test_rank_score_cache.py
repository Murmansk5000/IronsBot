from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ironsbot.integrations.storage.rank_page_cache import SqliteRankPageCache
from ironsbot.services.seer.rank_cache_queries import fetch_cached_score_segment
from ironsbot.services.seer.rank_models import (
    RankEntry,
    RankPageResult,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_score_cache import (
    cached_score_candidate_page_starts,
    fetch_rank_score_segment_from_cached_candidates,
)
from ironsbot.services.seer.rank_score_helpers import (
    score_segment_coverage,
    score_segment_sample_indexes,
)

PAGE_SIZE = 10
TARGET_SCORE = 150
OBSERVED_AT = 1781234567.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "start",
        "stop",
        "tie_start",
        "tie_stop",
        "size",
        "seeds",
        "budget",
        "confirmed",
        "cached_confirmed",
    ),
    [
        (0, 100, 20, 50, 100, [20], 1, False, False),
        (0, 100, 22, 25, 100, [20], 1, True, True),
        (0, 100, 0, 4, 100, [0], 1, True, True),
        (0, 100, 92, 100, 100, [90], 1, True, True),
        (0, 100, 22, 24, 24, [20], 1, True, False),
        (0, 100, 22, 30, 30, [20], 2, True, False),
        (23, 28, 20, 35, 100, [20], 1, True, True),
        (0, 100, 22, 44, 100, [20, 40], 2, False, False),
        (0, 100, 22, 44, 100, [20, 40], 3, True, True),
    ],
)
async def test_score_candidates_share_complete_coverage(  # noqa: PLR0913
    tmp_path: Path,
    start: int,
    stop: int,
    tie_start: int,
    tie_stop: int,
    size: int,
    seeds: list[int],
    budget: int,
    *,
    confirmed: bool,
    cached_confirmed: bool,
) -> None:
    pages = {
        page_start: RankPageResult(
            [
                RankEntry(
                    100000 + i,
                    "player",
                    200 if i < tie_start else TARGET_SCORE if i < tie_stop else 100,
                )
                for i in range(page_start, min(page_start + PAGE_SIZE, size))
            ],
            OBSERVED_AT + page_start,
        )
        for page_start in range(0, size + PAGE_SIZE, PAGE_SIZE)
    }
    cache = SqliteRankPageCache(
        tmp_path / "rank.sqlite", enabled=True, ttl_seconds=3600, allow_stale=True
    )
    for page_start, page in pages.items():
        cache.save(
            key=17,
            sub_key=0,
            start=page_start,
            end=page_start + PAGE_SIZE - 1,
            items=page.items,
            fetched_at=page.fetched_at,
        )

    calls: list[int] = []

    async def fetch_page(
        *_args: object, start: int, use_cache: bool, **_kwargs: object
    ) -> RankPageResult:
        assert not use_cache
        calls.append(start)
        return pages[start]

    result = RankScoreSearchResult("rank", "score", TARGET_SCORE, queried=True)
    online = await fetch_rank_score_segment_from_cached_candidates(
        None,
        key=17,
        sub_key=0,
        target_score=TARGET_SCORE,
        start_index=start,
        end_index=stop,
        result=result,
        candidate_starts=seeds,
        sample_limit=None,
        rank_page_size=lambda: PAGE_SIZE,
        rank_page_start=_rank_page_start,
        score_search_tie_page_limit=lambda: budget,
        fetch_rank_page_result=fetch_page,
    )
    assert (online is not None) is confirmed
    assert len(calls) == len(set(calls)) <= budget
    if online is None:
        assert result.items == [] and result.start_rank is None
        assert result.fetched_at is None
    cached = fetch_cached_score_segment(
        cache,
        key=17,
        sub_key=0,
        title="rank",
        score_name="score",
        target_score=TARGET_SCORE,
        search_limit=stop - start,
        start_index=start,
        sample_limit=None,
        page_size=PAGE_SIZE,
        page_start=_rank_page_start,
        tie_page_limit=budget,
        excluded_user_ids=(),
    )
    assert (cached is not None) is cached_confirmed
    if confirmed:
        expected = list(range(max(start, tie_start), min(stop, tie_stop)))
        assert online is not None
        for found in (online, cached):
            if found is None:
                continue
            assert [item.rank_index for item in found.items] == expected
            assert found.total_count == len(expected)
            assert (found.start_rank, found.end_rank) == (
                expected[0] + 1,
                expected[-1] + 1,
            )
        assert online.fetched_at == min(pages[i].fetched_at for i in calls)


@pytest.mark.parametrize(
    "fault", ["order", "duplicate", "terminal", "oversized", "alignment", "no_match"]
)
def test_score_coverage_rejects_contradictory_pages(fault: str) -> None:
    pages = {
        0: RankPageResult(
            [RankEntry(1, "a", 200), RankEntry(2, "b", 150)], OBSERVED_AT
        ),
        2: RankPageResult(
            [RankEntry(3, "c", 150), RankEntry(4, "d", 100)], OBSERVED_AT
        ),
    }
    coverage = score_segment_coverage(
        pages, start_index=0, end_index=4, page_size=2, target_score=TARGET_SCORE
    )
    assert coverage is not None and coverage.matches == (1, 2)
    assert coverage.missing_pages == ()
    if fault == "order":
        pages[2].items[0] = RankEntry(3, "c", 200)
    elif fault == "duplicate":
        pages[2].items[0] = RankEntry(2, "b", 150)
    elif fault == "terminal":
        pages[0].items.pop()
    elif fault == "oversized":
        pages[0].items.append(RankEntry(5, "e", 150))
    elif fault == "alignment":
        pages[1] = pages.pop(2)
    else:
        pages = {0: RankPageResult([RankEntry(1, "a", 200)], OBSERVED_AT)}
    assert (
        score_segment_coverage(
            pages, start_index=0, end_index=4, page_size=2, target_score=TARGET_SCORE
        )
        is None
    )


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
