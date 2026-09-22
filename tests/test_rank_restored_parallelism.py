from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ironsbot.services.seer.rank_models import (
    RankEntry,
    RankLookupResult,
    RankPageResult,
)
from ironsbot.services.seer.rank_position_cache import find_rank_by_cached_position
from ironsbot.services.seer.rank_score_search import (
    DescendingScoreSearchLimits,
    locate_descending_score_range,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("workers", [1, 2, 3])
@pytest.mark.parametrize("target", [200, 100, 50, 0, -1])
async def test_parallel_boundaries_match_sorted_list(workers: int, target: int) -> None:
    scores = [200 - index // 3 for index in range(603)]
    active = maximum = 0

    async def fetch(index: int) -> int | None:
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        try:
            await asyncio.sleep(0)
            return scores[index] if index < len(scores) else None
        finally:
            active -= 1

    result = await locate_descending_score_range(
        0,
        len(scores),
        target,
        fetch,
        limits=DescendingScoreSearchLimits(64, 100),
        parallelism=lambda: workers,
    )
    matches = [index for index, score in enumerate(scores) if score == target]
    assert (result.match_start, result.match_end) == (
        (matches[0], matches[-1] + 1) if matches else (None, None)
    )
    assert maximum <= workers
    if matches:
        assert maximum == workers


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError, ConnectionError])
async def test_recent_anchor_failure_returns_original_cache(
    error: type[Exception],
) -> None:
    cached_at = time.time() - 30
    cached = SimpleNamespace(rank_index=500, score=10, fetched_at=cached_at)
    fetch = AsyncMock(side_effect=error)
    result = await find_rank_by_cached_position(
        None,
        user_id=1,
        key=2,
        sub_key=0,
        page_size=100,
        result=RankLookupResult("rank", "score"),
        get_cached_rank_item=lambda **_: cached,
        rank_window_page_starts=lambda **_: [500, 400, 600],
        fetch_rank_page=fetch,
    )
    assert result is not None
    assert result.rank == cached.rank_index + 1
    assert result.fallback_cached_at == cached_at
    assert result.failure == "查询超时"
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_recent_successful_miss_continues_neighbor_search() -> None:
    starts: list[int] = []
    neighbor_start = 400

    async def fetch(_game: Any, **kwargs: Any) -> RankPageResult:
        starts.append(kwargs["start"])
        return RankPageResult(
            [RankEntry(1, "player", 10)] if kwargs["start"] == neighbor_start else [],
            time.time(),
        )

    result = await find_rank_by_cached_position(
        None,
        user_id=1,
        key=2,
        sub_key=0,
        page_size=100,
        result=RankLookupResult("rank", "score"),
        get_cached_rank_item=lambda **_: SimpleNamespace(
            rank_index=500,
            score=10,
            fetched_at=time.time(),
        ),
        rank_window_page_starts=lambda **_: [500, 400, 600],
        fetch_rank_page=fetch,
    )
    assert starts == [500, 400]
    assert result is not None and result.rank == starts[-1] + 1
    assert result.fallback_cached_at is None
