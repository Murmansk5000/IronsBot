import asyncio
from dataclasses import replace
from pathlib import Path
from time import time
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.integrations.storage.rank_page_cache import SqliteRankPageCache
from ironsbot.services.seer.rank import RankService
from ironsbot.services.seer.rank_exclusions import RankExclusionPolicy
from ironsbot.services.seer.rank_list_global_messages import format_global_rank_message
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS
from ironsbot.services.seer.rank_models import RankEntry
from ironsbot.services.seer.rank_pagination import RankPageConflictError

SIZE = 100
TOTAL = 10_100
DEEP_PLAYER = 5000
DEEP_PAGE = 4900
LAST_RANK = 10_000
MAX_ATTEMPTS = 2
TIE_PLAYERS = 3
NEIGHBOR_HIGH_END = 2
NEIGHBOR_LOW_END = 4
UNALIGNED_PAGE_SIZE = 64
BOUNDARY_PAGE = 960
GAME = cast("Any", None)


def service(
    tmp_path: Path, hidden: tuple[int, ...] = ()
) -> tuple[RankService, AsyncMock]:
    entries = [
        RankEntry(index + 1, f"player{index + 1}", TOTAL - index)
        for index in range(TOTAL)
    ]

    async def fetch(
        _game: Any, *, start: int, end: int, **_kwargs: Any
    ) -> list[RankEntry]:
        return entries[start : end + 1]

    transport = AsyncMock(side_effect=fetch)
    rank = RankService(
        RankQueryConfig(limit=TOTAL, online_limit=TOTAL, page_size=SIZE),
        SqliteRankPageCache(
            tmp_path / "rank.sqlite", enabled=True, ttl_seconds=3600, allow_stale=True
        ),
        lambda: None,
        transport,
        exclusions=RankExclusionPolicy(frozenset(hidden), {}),
    )
    return rank, transport


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rank_key", ["群星牌", "竞技段位", "狂野段位", "专家段位", "大师段位"]
)
async def test_official_rank_jumps_to_ten_thousand(
    tmp_path: Path, rank_key: str
) -> None:
    rank, transport = service(tmp_path, (1, 9999))
    result = await rank.fetch_visible_range_result(
        GAME, rank_key=rank_key, key=240, sub_key=1, start_rank=10_000, count=1
    )
    assert result.ranks == [10_000]
    assert [item.id for item in result.items] == [10_000]
    assert [call.kwargs["start"] for call in transport.await_args_list] == [9900]


@pytest.mark.asyncio
async def test_official_gaps_are_kept_in_text_and_cache(tmp_path: Path) -> None:
    rank, transport = service(tmp_path, (2,))
    result = await rank.fetch_visible_range_result(
        GAME, rank_key="群星牌", key=240, sub_key=1, start_rank=1, count=3
    )
    assert result.ranks == [1, 3]
    assert [item.id for item in result.items] == [1, 3]
    text = format_global_rank_message(
        GLOBAL_RANKS["群星牌"],
        result.items,
        timestamp="now",
        ranks=result.ranks,
        requested_count=3,
    )
    assert "1. player1" in text and "3. player3" in text
    assert "2. " not in text
    assert rank.cached_visible_range_result(
        rank_key="群星牌", key=240, sub_key=1, start_rank=1, count=3
    ) == replace(result, from_cache=True)
    transport.assert_awaited_once()


@pytest.mark.asyncio
async def test_collection_deep_jump_has_only_ten_prefix_pages(tmp_path: Path) -> None:
    rank, transport = service(tmp_path, (999, 1000, 1001, 5000))
    result = await rank.fetch_visible_range_result(
        GAME, rank_key="精灵图鉴", key=158, sub_key=1, start_rank=4998, count=1
    )
    assert result.ranks == [4998]
    assert (
        result.items[0].id == DEEP_PLAYER
    )  # Excluded ID outside the first 1000 remains visible.
    starts = [call.kwargs["start"] for call in transport.await_args_list]
    assert starts == [*range(0, 1000, SIZE), 4900]
    assert rank.cached_visible_range_result(
        rank_key="精灵图鉴", key=158, sub_key=1, start_rank=4998, count=1
    ) == replace(result, from_cache=True)


@pytest.mark.asyncio
async def test_collection_boundary_and_prefix_page_reuse(tmp_path: Path) -> None:
    rank, transport = service(tmp_path, (999, 1000, 1001))
    result = await rank.fetch_visible_range_result(
        GAME, rank_key="皮肤图鉴", key=159, sub_key=1, start_rank=998, count=4
    )
    assert [item.id for item in result.items] == [998, 1001, 1002, 1003]
    assert result.ranks == [998, 999, 1000, 1001]
    starts = [call.kwargs["start"] for call in transport.await_args_list]
    assert starts == list(range(0, 1100, SIZE))
    assert len(starts) == len(set(starts))


@pytest.mark.asyncio
async def test_collection_without_exclusions_jumps_directly(tmp_path: Path) -> None:
    rank, transport = service(tmp_path)
    result = await rank.fetch_visible_range_result(
        GAME, rank_key="精灵图鉴", key=158, sub_key=1, start_rank=10_000, count=1
    )
    assert result.items[0].id == LAST_RANK
    transport.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["target", "prefix"])
@pytest.mark.parametrize("permanent", [False, True])
async def test_conflict_retries_once_and_bypasses_cache(
    tmp_path: Path, *, phase: str, permanent: bool
) -> None:
    rank, transport = service(tmp_path, (99999,) if phase == "prefix" else ())
    attempts = 0
    original = transport.side_effect

    async def fetch(
        game: Any, *, start: int, end: int, **kwargs: Any
    ) -> list[RankEntry]:
        nonlocal attempts
        entries = await original(game, start=start, end=end, **kwargs)
        if start == 0:
            attempts += 1
        if start == SIZE and (attempts == 1 or permanent):
            entries[0] = RankEntry(1, "moved", TOTAL)
        return entries

    transport.side_effect = fetch
    query = rank.fetch_visible_range_result(
        GAME,
        rank_key="精灵图鉴" if phase == "prefix" else "群星牌",
        key=158,
        sub_key=1,
        start_rank=1,
        count=SIZE + 1,
    )
    if permanent:
        with pytest.raises(RankPageConflictError):
            await query
    else:
        result = await query
        assert len(result.items) == SIZE + 1
    assert attempts == MAX_ATTEMPTS
    assert transport.await_count == MAX_ATTEMPTS * 2


@pytest.mark.asyncio
async def test_target_retry_does_not_reload_valid_prefix(tmp_path: Path) -> None:
    rank, transport = service(tmp_path, (1,))
    original = transport.side_effect
    attempts = 0

    async def fetch(
        game: Any, *, start: int, end: int, **kwargs: Any
    ) -> list[RankEntry]:
        nonlocal attempts
        entries = await original(game, start=start, end=end, **kwargs)
        if start == DEEP_PAGE:
            attempts += 1
        if start == DEEP_PLAYER and attempts == 1:
            entries[0] = RankEntry(4901, "duplicate", entries[0].score)
        return entries

    transport.side_effect = fetch
    result = await rank.fetch_visible_range_result(
        GAME, rank_key="精灵图鉴", key=158, sub_key=1, start_rank=4998, count=5
    )
    assert result.ranks == list(range(4998, 5003))
    assert [call.kwargs["start"] for call in transport.await_args_list] == [
        *range(0, 1000, SIZE),
        4900,
        5000,
        4900,
        5000,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "player_id,expected", [(1000, None), (1001, 1000), (5000, 4999)]
)
async def test_collection_player_lookup_obeys_prefix_boundary(
    tmp_path: Path, player_id: int, expected: int | None
) -> None:
    rank, _ = service(tmp_path, (1000, 1001, 5000))
    result = await rank.find_rank(
        GAME,
        user_id=player_id,
        key=158,
        sub_key=1,
        title="精灵图鉴",
        score_name="项",
        target_score=TOTAL - player_id + 1,
    )
    assert result.rank == expected
    assert result.excluded is (expected is None)


@pytest.mark.asyncio
async def test_collection_score_query_and_cache_use_same_boundary(
    tmp_path: Path,
) -> None:
    rank, _ = service(tmp_path, (1, 5000))
    result = await rank.fetch_score_segment(
        GAME,
        rank_key="精灵图鉴",
        key=158,
        sub_key=1,
        title="精灵图鉴",
        score_name="项",
        target_score=TOTAL - 4999,
    )
    assert [(item.id, item.rank_index) for item in result.items] == [(5000, 4998)]
    cached = rank.cached_score_segment(
        rank_key="精灵图鉴",
        key=158,
        sub_key=1,
        title="精灵图鉴",
        score_name="项",
        target_score=TOTAL - 4999,
    )
    assert cached is not None
    assert cached.items == result.items


@pytest.mark.asyncio
async def test_stale_prefix_is_not_used_for_cached_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rank, _ = service(tmp_path, (1,))
    await rank.fetch_visible_range_result(
        GAME, rank_key="精灵图鉴", key=158, sub_key=1, start_rank=5000, count=1
    )
    monkeypatch.setattr("time.time", lambda: time() + 7200)
    assert (
        rank.cached_visible_range_result(
            rank_key="精灵图鉴", key=158, sub_key=1, start_rank=5000, count=1
        )
        is None
    )


@pytest.mark.asyncio
async def test_conflict_retry_keeps_callers_deadline(tmp_path: Path) -> None:
    rank, transport = service(tmp_path)
    original = transport.side_effect
    attempts = 0

    async def fetch(
        game: Any, *, start: int, end: int, **kwargs: Any
    ) -> list[RankEntry]:
        nonlocal attempts
        if start == 0:
            attempts += 1
            if attempts > 1:
                await asyncio.Event().wait()
        rows = await original(game, start=start, end=end, **kwargs)
        if start == SIZE:
            rows[0] = RankEntry(1, "duplicate", TOTAL)
        return rows

    transport.side_effect = fetch
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await rank.fetch_visible_range_result(
                GAME,
                rank_key="群星牌",
                key=240,
                sub_key=1,
                start_rank=1,
                count=SIZE + 1,
            )
    assert attempts == MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_official_score_gaps_preserve_numbers(tmp_path: Path) -> None:
    rank, transport = service(tmp_path, (2,))

    async def fetch(
        _game: Any, *, start: int, end: int, **_kwargs: Any
    ) -> list[RankEntry]:
        return [
            RankEntry(i, f"player{i}", 100 if i <= TIE_PLAYERS else 99)
            for i in range(start + 1, min(end + 2, 5))
        ]

    transport.side_effect = fetch
    result = await rank.fetch_score_segment(
        GAME,
        rank_key="群星牌",
        key=240,
        sub_key=1,
        title="群星牌",
        score_name="分",
        target_score=100,
    )
    assert [(item.id, item.rank_index) for item in result.items] == [(1, 0), (3, 2)]
    assert (result.start_rank, result.end_rank, result.total_count) == (1, 3, 2)


@pytest.mark.asyncio
async def test_collection_neighbor_scores_use_same_offset(tmp_path: Path) -> None:
    rank, transport = service(tmp_path, (1,))

    async def fetch(
        _game: Any, *, start: int, end: int, **_kwargs: Any
    ) -> list[RankEntry]:
        return [
            RankEntry(
                i,
                f"player{i}",
                100 if i <= NEIGHBOR_HIGH_END else 98 if i <= NEIGHBOR_LOW_END else 97,
            )
            for i in range(start + 1, min(end + 2, SIZE + 1))
        ]

    transport.side_effect = fetch
    result = await rank.fetch_score_segment(
        GAME,
        rank_key="成就点数",
        key=17,
        sub_key=0,
        title="成就",
        score_name="点",
        target_score=99,
    )
    assert result.higher_gap is not None and result.lower_gap is not None
    assert [(item.id, item.rank_index) for item in result.higher_gap.items] == [(2, 0)]
    assert [(item.id, item.rank_index) for item in result.lower_gap.items] == [
        (3, 1),
        (4, 2),
    ]
    cached = rank.cached_score_segment(
        rank_key="成就点数",
        key=17,
        sub_key=0,
        title="成就",
        score_name="点",
        target_score=99,
    )
    assert cached is not None
    assert cached.higher_gap == result.higher_gap
    assert cached.lower_gap == result.lower_gap


@pytest.mark.asyncio
async def test_boundary_page_retry_refreshes_overlapping_prefix(tmp_path: Path) -> None:
    rank, transport = service(tmp_path, (1000,))
    rank = replace(
        rank, config=rank.config.model_copy(update={"page_size": UNALIGNED_PAGE_SIZE})
    )
    original = transport.side_effect
    boundary_attempts = 0

    async def fetch(
        game: Any, *, start: int, end: int, **kwargs: Any
    ) -> list[RankEntry]:
        nonlocal boundary_attempts
        rows = await original(game, start=start, end=end, **kwargs)
        if start == BOUNDARY_PAGE:
            boundary_attempts += 1
            if boundary_attempts == 1:
                rows[1000 - start] = RankEntry(1, "moved", rows[1000 - start].score)
        return rows

    transport.side_effect = fetch
    result = await rank.fetch_visible_range_result(
        GAME, rank_key="精灵图鉴", key=158, sub_key=1, start_rank=998, count=3
    )
    assert [item.id for item in result.items] == [998, 999, 1001]
    assert result.ranks == [998, 999, 1000]
    assert boundary_attempts == MAX_ATTEMPTS
