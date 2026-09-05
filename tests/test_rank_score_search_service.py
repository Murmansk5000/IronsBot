import pytest

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.services.seer.rank_list_models import GlobalRankSpec
from ironsbot.services.seer.rank_list_score_messages import (
    format_global_rank_score_message,
)
from ironsbot.services.seer.rank_models import RankEntry, RankPageResult
from ironsbot.services.seer.rank_score_search import (
    DescendingScoreSearchLimits,
    locate_descending_score_range,
    score_search_probe_limit,
    score_search_tie_page_limit,
)
from ironsbot.services.seer.rank_score_segments import (
    RankScoreSegmentDependencies,
    fetch_rank_score_segment,
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
SHORT_SEGMENT_START = 6
SHORT_SEGMENT_END = 9
OBSERVED_AT = 1781234567.0


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["boundary", "lower", "upper", "confirmed", "below"])
async def test_score_service_preserves_search_completion(stage: str) -> None:
    page_size = 10
    size = 1 if stage == "boundary" else 100
    probes = 6 if stage == "upper" else 32 if stage == "confirmed" else 1
    target = 99 if stage == "below" else 150
    calls: list[int] = []

    async def no_candidates(*_args: object, **_kwargs: object) -> None:
        return None

    async def page(
        *_args: object, start: int, end: int, **_kwargs: object
    ) -> RankPageResult:
        calls.append(start)
        return RankPageResult(
            [
                RankEntry(
                    i,
                    "player",
                    200
                    if i < SHORT_SEGMENT_START
                    else 150
                    if i < SHORT_SEGMENT_END
                    else 100,
                )
                for i in range(start, min(end + 1, size))
            ],
            OBSERVED_AT,
        )

    result = await fetch_rank_score_segment(
        None,
        key=17,
        sub_key=0,
        title="rank",
        score_name="score",
        target_score=target,
        deps=RankScoreSegmentDependencies(
            score_search_limit=lambda _limit: 100,
            rank_page_size=lambda: page_size,
            rank_page_start=lambda i: i // page_size * page_size,
            cached_score_candidate_page_starts=lambda **_kwargs: [],
            fetch_cached_candidates=no_candidates,
            score_search_probe_limit=lambda _limit: probes,
            score_search_tie_page_limit=lambda: 1,
            fetch_rank_page_result=page,
            score_miss_proof_from_page=lambda **_kwargs: None,
        ),
    )
    message = format_global_rank_score_message(
        GlobalRankSpec("rank", key=17, sub_key=0, unit="score"),
        result,
        timestamp="source-time",
    )
    exhausted = stage in ("boundary", "lower", "upper")
    if exhausted:
        assert "探针上限" in message
        assert "完整同分范围尚未确认" in message
        assert "没有" not in message and "找不到" not in message
    assert result.budget_exhausted is exhausted
    assert result.fetched_at == OBSERVED_AT
    assert len(calls) <= probes * 3 + 1
    if stage == "upper":
        assert [item.rank_index for item in result.items] == [6, 7, 8]
        assert result.total_count == len(result.items)
        assert result.end_rank == result.items[-1].rank_index + 1
        assert "已确认 3 人" in message
        assert "第 7-16 名" not in message and "共 10 人" not in message
    elif stage == "confirmed":
        assert (result.start_rank, result.end_rank, result.total_count) == (7, 9, 3)
        assert "第 7-9 名，共 3 人" in message
    elif stage == "below":
        assert "不在" in message and len(calls) == 1
    else:
        assert not result.items


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
