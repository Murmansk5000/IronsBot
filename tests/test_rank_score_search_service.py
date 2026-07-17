import pytest

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.services.seer.rank_score_search import (
    DescendingScoreSearchLimits,
    locate_descending_score_range,
    score_search_probe_limit,
    score_search_tie_page_limit,
)

SMALL_LIMIT = 10
PROBE_LIMIT = 32
TIE_PAGE_LIMIT = 5
MISSING_BOUNDARY_INDEX = 5
LAST_INDEX = 2
BOUNDARY_SCORE = 80
LARGE_LIMIT = 50_000
LIMITED_PROBE_COUNT = 16
LARGE_SEGMENT_START = 856
LARGE_SEGMENT_END = 1156
LARGE_SEGMENT_SCORE = 200050


def test_score_search_limits_respect_config_bounds() -> None:
    config = RankQueryConfig(
        score_search_probe_limit=PROBE_LIMIT,
        score_search_tie_page_limit=TIE_PAGE_LIMIT,
    )

    assert score_search_probe_limit(config, SMALL_LIMIT) == SMALL_LIMIT
    assert score_search_probe_limit(config, 100) == PROBE_LIMIT
    assert score_search_tie_page_limit(config) == TIE_PAGE_LIMIT


@pytest.mark.asyncio
async def test_score_range_search_binary_searches_missing_tail() -> None:
    scores = {0: 100, 1: 90, 2: 80}
    probes: list[int] = []

    async def score_at(index: int) -> int | None:
        probes.append(index)
        return scores.get(index)

    result = await locate_descending_score_range(
        0,
        6,
        90,
        score_at,
        limits=DescendingScoreSearchLimits(
            probe_count=PROBE_LIMIT,
            tie_fallback_size=SMALL_LIMIT,
        ),
    )

    assert result.last_index == LAST_INDEX
    assert result.boundary_score == BOUNDARY_SCORE
    assert result.match_start == 1
    assert result.match_end == LAST_INDEX
    assert MISSING_BOUNDARY_INDEX in probes


@pytest.mark.asyncio
async def test_score_range_search_returns_missing_score_insertion_index() -> None:
    scores = [100, 90, 80]

    async def score_at(index: int) -> int | None:
        return scores[index]

    result = await locate_descending_score_range(
        0,
        len(scores),
        95,
        score_at,
        limits=DescendingScoreSearchLimits(
            probe_count=PROBE_LIMIT,
            tie_fallback_size=SMALL_LIMIT,
        ),
    )

    assert result.match_start is None
    assert result.match_end is None
    assert result.insertion_index == 1


@pytest.mark.asyncio
async def test_score_range_search_gives_each_binary_boundary_its_own_budget() -> None:
    probes: list[int] = []

    async def score_at(index: int) -> int:
        probes.append(index)
        if index < LARGE_SEGMENT_START:
            return LARGE_SEGMENT_SCORE + 1
        if index < LARGE_SEGMENT_END:
            return LARGE_SEGMENT_SCORE
        return LARGE_SEGMENT_SCORE - 1

    result = await locate_descending_score_range(
        0,
        LARGE_LIMIT,
        LARGE_SEGMENT_SCORE,
        score_at,
        limits=DescendingScoreSearchLimits(
            probe_count=LIMITED_PROBE_COUNT,
            tie_fallback_size=300,
        ),
    )

    assert result.match_start == LARGE_SEGMENT_START
    assert result.match_end == LARGE_SEGMENT_END
    assert not result.truncated
    assert not result.budget_exhausted
    assert len(probes) <= LIMITED_PROBE_COUNT * 3
