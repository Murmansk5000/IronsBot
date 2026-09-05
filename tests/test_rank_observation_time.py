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
from ironsbot.services.seer.rank_models import RankEntry, RankPageResult

PLAYER_ID = 712345678
SOURCE_TIME = 1_781_234_567.0
TARGET_INDEX = 19
LIMIT = 100
PAGE_SIZE = 10


def _service(tmp_path: Path) -> RankService:
    cache = SqliteRankPageCache(
        tmp_path / "rank.sqlite",
        enabled=True,
        ttl_seconds=3600,
        allow_stale=True,
    )
    return RankService(
        RankQueryConfig(limit=LIMIT, online_limit=LIMIT, page_size=PAGE_SIZE),
        cache,
        lambda: None,
        AsyncMock(side_effect=AssertionError("unexpected transport")),
        exclusions=RankExclusionPolicy(frozenset(), {}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["anchor", "linear", "score"])
async def test_lookup_preserves_original_page_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    rank = _service(tmp_path)
    if mode == "anchor":
        rank.cache.save(
            key=240,
            sub_key=1,
            start=TARGET_INDEX,
            end=TARGET_INDEX,
            items=[RankEntry(PLAYER_ID, "cached", 100)],
            fetched_at=time() - 10,
        )
    calls: list[int] = []

    async def page(
        _self: Any, _game: Any, *, start: int, end: int, **_kwargs: Any
    ) -> RankPageResult:
        calls.append(start)
        return RankPageResult(
            [
                RankEntry(
                    PLAYER_ID if index == TARGET_INDEX else index,
                    "player",
                    LIMIT - index,
                )
                for index in range(start, min(end + 1, LIMIT))
            ],
            SOURCE_TIME + len(calls) - 1,
            from_cache=True,
        )

    monkeypatch.setattr(RankService, "fetch_page_result", page)
    result = await rank.find_rank(
        cast("Any", None),
        user_id=PLAYER_ID,
        title="rank",
        score_name="score",
        key=240,
        sub_key=1,
        target_score=LIMIT - TARGET_INDEX if mode == "score" else None,
    )
    assert result.rank == TARGET_INDEX + 1
    assert result.fetched_at == SOURCE_TIME
    assert result.cost.cache_page_hits == len(calls)
    assert result.cost.online_page_fetches == 0
    if mode == "score":
        assert calls[0] == LIMIT - PAGE_SIZE
    elif mode == "anchor":
        assert calls == [PAGE_SIZE]


@pytest.mark.asyncio
async def test_cached_hit_miss_and_timeout_keep_sqlite_time(
    tmp_path: Path,
) -> None:
    rank = _service(tmp_path)
    stamp = time() - 120
    rank.cache.save(
        key=240,
        sub_key=1,
        start=0,
        end=0,
        items=[RankEntry(PLAYER_ID, "cached", 100)],
        fetched_at=stamp,
    )
    rank.cache.save_miss(
        key=240,
        sub_key=1,
        user_id=PLAYER_ID + 1,
        searched_limit=LIMIT,
        fetched_at=stamp,
    )
    for player_id in (PLAYER_ID, PLAYER_ID + 1):
        cached = rank.cached_player_lookup(
            rank_key="群星牌",
            user_id=player_id,
            title="rank",
            score_name="score",
            key=240,
            sub_key=1,
        )
        assert cached is not None
        assert cached[1].fetched_at == stamp
    miss = await rank.find_rank(
        cast("Any", None),
        user_id=PLAYER_ID + 1,
        title="rank",
        score_name="score",
        key=240,
        sub_key=1,
    )
    assert miss.fetched_at == stamp
    cast("AsyncMock", rank.fetch_online_page).assert_not_awaited()
    offline = replace(rank, fetch_online_page=AsyncMock(side_effect=TimeoutError))
    fallback = await offline.find_rank(
        cast("Any", None),
        user_id=PLAYER_ID,
        title="rank",
        score_name="score",
        key=240,
        sub_key=1,
    )
    assert fallback.rank == 1
    assert fallback.failure == "查询超时"
    assert fallback.fetched_at == fallback.fallback_cached_at == stamp


@pytest.mark.asyncio
async def test_persisted_linear_miss_keeps_oldest_page_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rank = _service(tmp_path)
    stamp = time() - 120

    async def page(
        _self: Any, _game: Any, *, start: int, end: int, **_kwargs: Any
    ) -> RankPageResult:
        return RankPageResult(
            [
                RankEntry(index, "player", LIMIT - index)
                for index in range(start, end + 1)
            ],
            stamp + start,
        )

    monkeypatch.setattr(RankService, "fetch_page_result", page)
    result = await rank.find_rank(
        cast("Any", None),
        user_id=PLAYER_ID,
        title="rank",
        score_name="score",
        key=240,
        sub_key=1,
    )
    assert result.fetched_at == stamp
    stored = rank.cache.miss(key=240, sub_key=1, user_id=PLAYER_ID, minimum_limit=LIMIT)
    assert stored is not None
    assert stored.fetched_at == stamp


@pytest.mark.asyncio
async def test_visible_rank_includes_adjustment_page_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rank = replace(
        _service(tmp_path), exclusions=RankExclusionPolicy(frozenset({0}), {})
    )
    rank.cache.save(
        key=240,
        sub_key=1,
        start=TARGET_INDEX,
        end=TARGET_INDEX,
        items=[RankEntry(PLAYER_ID, "cached", 100)],
        fetched_at=time() - 10,
    )

    async def page(
        _self: Any, _game: Any, *, start: int, end: int, **_kwargs: Any
    ) -> RankPageResult:
        return RankPageResult(
            [
                RankEntry(
                    PLAYER_ID if index == TARGET_INDEX else index,
                    "player",
                    LIMIT - index,
                )
                for index in range(start, end + 1)
            ],
            SOURCE_TIME + start,
        )

    monkeypatch.setattr(RankService, "fetch_page_result", page)
    result = await rank.find_rank(
        cast("Any", None),
        user_id=PLAYER_ID,
        title="rank",
        score_name="score",
        key=240,
        sub_key=1,
    )
    assert result.rank == TARGET_INDEX
    assert result.fetched_at == SOURCE_TIME
    assert result.cost.lightweight_confirmed  # Existing anchor quota classification.
