from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ironsbot.services.seer.rank_models import RankPageResult
from ironsbot.services.seer.rank_score_segments import (
    RankScoreSegmentDependencies,
    fetch_rank_score_segment,
)

PAGE_SIZE = 10
PARALLELISM = 3
SCORE_START_INDEX = 30
SCORE_END_INDEX = 60


@pytest.mark.asyncio
async def test_score_segment_uses_parallel_probes_and_tie_page_batches() -> None:
    scores = [600] * SCORE_START_INDEX + [500] * 30 + [400] * 40
    item_batches: list[tuple[int, ...]] = []
    page_batches: list[tuple[int, ...]] = []

    def item_at(index: int) -> Any | None:
        if not 0 <= index < len(scores):
            return None
        return SimpleNamespace(id=index, nick=f"玩家{index}", score=scores[index])

    async def fetch_item(*_args: Any, index: int, **_kwargs: Any) -> Any | None:
        return item_at(index)

    async def fetch_items(
        *_args: Any,
        indexes: tuple[int, ...],
        **_kwargs: Any,
    ) -> list[Any | None]:
        item_batches.append(indexes)
        return [item_at(index) for index in indexes]

    async def fetch_page_result(
        *_args: Any,
        start: int,
        **_kwargs: Any,
    ) -> RankPageResult:
        return RankPageResult(
            [
                item_at(index)
                for index in range(start, min(start + PAGE_SIZE, len(scores)))
            ],
            fetched_at=1.0,
        )

    async def fetch_page_results(
        *_args: Any,
        starts: tuple[int, ...],
        **_kwargs: Any,
    ) -> list[RankPageResult]:
        page_batches.append(starts)
        return [await fetch_page_result(start=start) for start in starts]

    result = await fetch_rank_score_segment(
        object(),
        key=1,
        sub_key=0,
        title="测试榜",
        score_name="分",
        target_score=500,
        deps=RankScoreSegmentDependencies(
            score_search_limit=lambda _limit: 100,
            rank_page_size=lambda: PAGE_SIZE,
            rank_page_start=lambda index: index // PAGE_SIZE * PAGE_SIZE,
            cached_score_candidate_page_starts=lambda **_kwargs: [],
            fetch_cached_candidates=lambda *_args, **_kwargs: _none(),
            score_search_probe_limit=lambda _limit: 40,
            score_search_tie_page_limit=lambda: 5,
            fetch_rank_item=fetch_item,
            fetch_rank_items=fetch_items,
            fetch_rank_page_result=fetch_page_result,
            fetch_rank_page_results=fetch_page_results,
            score_miss_proof_from_page=lambda **_kwargs: None,
            parallelism=PARALLELISM,
        ),
    )

    assert result.start_rank == SCORE_START_INDEX + 1
    assert result.end_rank == SCORE_END_INDEX
    assert [item.rank_index for item in result.items] == list(
        range(SCORE_START_INDEX, SCORE_END_INDEX)
    )
    assert max(len(batch) for batch in item_batches) == PARALLELISM
    assert page_batches == [(30, 40, 50)]


async def _none() -> None:
    return None
