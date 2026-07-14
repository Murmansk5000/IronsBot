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
