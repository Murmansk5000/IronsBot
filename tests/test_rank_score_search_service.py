import pytest

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.services.seer.rank_score_search import (
    find_last_existing_score_index,
    score_search_probe_limit,
    score_search_tie_page_limit,
)

SMALL_LIMIT = 10
PROBE_LIMIT = 32
TIE_PAGE_LIMIT = 5
MISSING_BOUNDARY_INDEX = 5


def test_score_search_limits_respect_config_bounds() -> None:
    config = RankQueryConfig(
        score_search_probe_limit=PROBE_LIMIT,
        score_search_tie_page_limit=TIE_PAGE_LIMIT,
    )

    assert score_search_probe_limit(config, SMALL_LIMIT) == SMALL_LIMIT
    assert score_search_probe_limit(config, 100) == PROBE_LIMIT
    assert score_search_tie_page_limit(config) == TIE_PAGE_LIMIT


@pytest.mark.asyncio
async def test_find_last_existing_score_index_binary_searches_missing_tail() -> None:
    scores = {0: 100, 1: 90, 2: 80}
    probes: list[int] = []

    async def score_at(index: int) -> int | None:
        probes.append(index)
        return scores.get(index)

    assert await find_last_existing_score_index(0, 6, score_at) == (2, 80)
    assert MISSING_BOUNDARY_INDEX in probes
