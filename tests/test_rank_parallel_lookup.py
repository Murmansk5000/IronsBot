from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from ironsbot.services.seer.rank_models import (
    RankEntry,
    RankLookupResult,
    RankPageResult,
)
from ironsbot.services.seer.rank_player_scheduler import PlayerRankPagePriority
from ironsbot.services.seer.rank_position_cache import find_rank_by_cached_position
from ironsbot.services.seer.rank_score_lookup import find_rank_by_linear_scan

TARGET_ID = 999
TARGET_INDEX = 350
TARGET_RANK = TARGET_INDEX + 1
EXPANDED_TARGET_START = 400
EXPANDED_TARGET_RANK = EXPANDED_TARGET_START + 1


@pytest.mark.asyncio
async def test_linear_player_lookup_scans_contiguous_pages_in_parallel_batches(
) -> None:
    batches: list[tuple[int, ...]] = []

    async def fetch_pages(
        _game: Any,
        *,
        starts: tuple[int, ...],
        **_kwargs: Any,
    ) -> list[list[RankEntry]]:
        batches.append(starts)
        return [
            [
                RankEntry(
                    id=TARGET_ID if index == TARGET_INDEX else index,
                    nick=str(index),
                    score=1_000 - index,
                )
                for index in range(start, start + 100)
            ]
            for start in starts
        ]

    async def fetch_page(*_args: Any, **_kwargs: Any) -> list[Any]:
        return []

    result = await find_rank_by_linear_scan(
        object(),
        user_id=TARGET_ID,
        key=1,
        sub_key=0,
        limit=500,
        page_size=100,
        result=RankLookupResult(title="测试榜", score_name="分"),
        fetch_rank_page=fetch_page,
        fetch_rank_pages=fetch_pages,
        parallelism=3,
    )

    assert result.rank == TARGET_RANK
    assert batches == [(0, 100, 200), (300, 400)]


@pytest.mark.asyncio
async def test_cached_rank_checks_anchor_before_parallel_expansion() -> None:
    calls: list[tuple[str, tuple[int, ...]]] = []
    cached = SimpleNamespace(rank_index=250, score=100)

    async def fetch_page(
        _game: Any,
        *,
        start: int,
        **_kwargs: Any,
    ) -> RankPageResult:
        calls.append(("anchor", (start,)))
        return RankPageResult([], fetched_at=0.0)

    async def fetch_pages(
        _game: Any,
        *,
        starts: tuple[int, ...],
        **_kwargs: Any,
    ) -> list[RankPageResult]:
        calls.append(("batch", starts))
        return [
            RankPageResult(
                [
                    RankEntry(
                        id=(
                            TARGET_ID
                            if start == EXPANDED_TARGET_START and offset == 0
                            else start + offset
                        ),
                        nick=str(start + offset),
                        score=100,
                    )
                    for offset in range(100)
                ],
                fetched_at=0.0,
            )
            for start in starts
        ]

    result = RankLookupResult(title="测试榜", score_name="分")
    found = await find_rank_by_cached_position(
        object(),
        user_id=TARGET_ID,
        key=1,
        sub_key=0,
        page_size=100,
        result=result,
        get_cached_rank_item=lambda **_kwargs: cached,
        rank_window_page_starts=lambda **_kwargs: [200, 100, 300, 400],
        fetch_rank_page=fetch_page,
        fetch_rank_pages=fetch_pages,
        parallelism=2,
    )

    assert found is result
    assert result.rank == EXPANDED_TARGET_RANK
    assert calls == [
        ("anchor", (200,)),
        ("batch", (100, 300)),
        ("batch", (400,)),
    ]


@pytest.mark.asyncio
async def test_recent_cached_rank_falls_back_after_one_short_anchor_timeout() -> None:
    cached = SimpleNamespace(
        rank_index=250,
        score=100,
        fetched_at=time.time(),
    )
    request_options: list[dict[str, Any]] = []

    async def timeout_anchor(*_args: Any, **kwargs: Any) -> RankPageResult:
        request_options.append(kwargs)
        raise TimeoutError

    result = RankLookupResult(title="测试榜", score_name="分")
    found = await find_rank_by_cached_position(
        object(),
        user_id=TARGET_ID,
        key=1,
        sub_key=0,
        page_size=100,
        result=result,
        get_cached_rank_item=lambda **_kwargs: cached,
        rank_window_page_starts=lambda **_kwargs: [200, 100, 300],
        fetch_rank_page=timeout_anchor,
        recent_cache_max_age_seconds=600,
        recent_cache_anchor_timeout_seconds=5,
    )

    assert found is result
    assert result.rank == cached.rank_index + 1
    assert result.score == cached.score
    assert result.failure == "查询超时"
    assert result.cost.used_recent_cache_anchor
    assert result.cost.used_recent_cache_fallback
    assert request_options == [
        {
            "key": 1,
            "sub_key": 0,
            "start": 200,
            "end": 299,
            "use_cache": False,
            "page_phase": "recent_anchor",
            "page_priority": PlayerRankPagePriority.RECENT_CACHE_ANCHOR,
            "page_timeout_seconds": 5,
            "page_max_retries": 0,
        }
    ]


@pytest.mark.asyncio
async def test_old_cached_rank_keeps_normal_anchor_failure_behavior() -> None:
    cached = SimpleNamespace(
        rank_index=250,
        score=100,
        fetched_at=time.time() - 601,
    )
    request_options: list[dict[str, Any]] = []

    async def timeout_anchor(*_args: Any, **kwargs: Any) -> RankPageResult:
        request_options.append(kwargs)
        raise TimeoutError

    with pytest.raises(TimeoutError):
        await find_rank_by_cached_position(
            object(),
            user_id=TARGET_ID,
            key=1,
            sub_key=0,
            page_size=100,
            result=RankLookupResult(title="测试榜", score_name="分"),
            get_cached_rank_item=lambda **_kwargs: cached,
            rank_window_page_starts=lambda **_kwargs: [200, 100, 300],
            fetch_rank_page=timeout_anchor,
            recent_cache_max_age_seconds=600,
            recent_cache_anchor_timeout_seconds=5,
        )

    assert request_options[0]["page_phase"] == "cached_anchor"
    assert request_options[0]["page_priority"] == PlayerRankPagePriority.CACHED_ANCHOR
    assert request_options[0]["page_timeout_seconds"] is None
    assert request_options[0]["page_max_retries"] is None
