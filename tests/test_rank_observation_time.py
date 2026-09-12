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
from ironsbot.services.seer.rank_list_formatting import timestamp_text
from ironsbot.services.seer.rank_list_global_messages import format_global_rank_message
from ironsbot.services.seer.rank_list_models import GlobalRankSpec
from ironsbot.services.seer.rank_list_score_messages import (
    format_global_rank_score_message,
)
from ironsbot.services.seer.rank_models import (
    RankEntry,
    RankPageResult,
    RankScoreSearchItem,
    RankScoreSearchResult,
)
from ironsbot.services.seer.rank_pagination import RankPageConflictError

PLAYER_ID = 712345678
SOURCE_TIME = 1_781_234_567.0
TARGET_INDEX = 19
LIMIT = 100
PAGE_SIZE = 10
CACHE_TTL_SECONDS = 3600
CONFIRMED_SCORE = 101
TIE_START = 20
TIE_END = 40


@pytest.mark.asyncio
@pytest.mark.parametrize("excluded", [False, True])
@pytest.mark.parametrize("conflict", ["duplicate", "inversion"])
async def test_range_rejects_moving_pages_before_numbering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    excluded: bool,
    conflict: str,
) -> None:
    rank = replace(
        _service(tmp_path),
        exclusions=RankExclusionPolicy(
            frozenset((999_999,)) if excluded else frozenset(), {}
        ),
    )
    calls: list[int] = []

    async def page(
        _self: Any, _game: Any, *, start: int, end: int, **_: Any
    ) -> RankPageResult:
        calls.append(start)
        items = _score_entries(start, end)
        if start == PAGE_SIZE:
            items[0] = RankEntry(
                100_000 if conflict == "duplicate" else 999_998,
                "moved",
                201 if conflict == "inversion" else 200,
            )
        return RankPageResult(items, SOURCE_TIME + start)

    monkeypatch.setattr(RankService, "fetch_page_result", page)
    with pytest.raises(RankPageConflictError):
        await rank.fetch_visible_range_result(
            cast("Any", None),
            rank_key="成就点数",
            key=17,
            sub_key=0,
            start_rank=1,
            count=PAGE_SIZE + 1,
        )
    assert calls == [0, PAGE_SIZE]


@pytest.mark.asyncio
async def test_conflicting_linear_scan_does_not_save_missing_player(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rank = _service(tmp_path)
    calls: list[int] = []

    async def page(
        _self: Any, _game: Any, *, start: int, end: int, **_: Any
    ) -> RankPageResult:
        calls.append(start)
        items = _score_entries(start, end)
        if start == PAGE_SIZE:
            items[0] = RankEntry(100_000, "moved", 200)
        return RankPageResult(items, SOURCE_TIME + start)

    monkeypatch.setattr(RankService, "fetch_page_result", page)
    result = await rank.find_rank(
        cast("Any", None),
        user_id=PLAYER_ID,
        key=17,
        sub_key=0,
        title="rank",
        score_name="score",
    )
    assert result.rank is None
    assert result.failure is not None and "发生变化" in result.failure
    assert calls == [0, PAGE_SIZE]
    assert (
        rank.cache.miss(key=17, sub_key=0, user_id=PLAYER_ID, minimum_limit=1) is None
    )


@pytest.mark.parametrize("excluded", [False, True])
def test_cache_only_window_rejects_player_moving_between_page_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    excluded: bool,
) -> None:
    rank = replace(
        _service(tmp_path),
        exclusions=RankExclusionPolicy(
            frozenset((999_999,)) if excluded else frozenset(), {}
        ),
    )
    for start in (0, PAGE_SIZE):
        rank.cache.save(
            key=17,
            sub_key=0,
            start=start,
            end=start + PAGE_SIZE - 1,
            items=_score_entries(start, start + PAGE_SIZE - 1),
            fetched_at=SOURCE_TIME,
        )
    read_page = SqliteRankPageCache.page

    def page(cache: SqliteRankPageCache, **kwargs: Any) -> Any:
        result = read_page(cache, **kwargs)
        if kwargs["start"] == 0:
            moved = _score_entries(PAGE_SIZE, PAGE_SIZE * 2 - 1)
            moved[0] = RankEntry(100_000, "moved", 200)
            cache.save(
                key=17,
                sub_key=0,
                start=PAGE_SIZE,
                end=PAGE_SIZE * 2 - 1,
                items=moved,
                fetched_at=SOURCE_TIME + 60,
            )
        return result

    monkeypatch.setattr(SqliteRankPageCache, "page", page)
    assert (
        rank.cached_visible_range_result(
            rank_key="成就点数", key=17, sub_key=0, start_rank=1, count=PAGE_SIZE + 1
        )
        is None
    )


def _score_entries(start: int, end: int) -> list[RankEntry]:
    return [
        RankEntry(
            100_000 + index,
            "player",
            200 if index < TIE_START else 150 if index < TIE_END else 100,
        )
        for index in range(start, end + 1)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_empty", [False, True])
async def test_raw_window_keeps_oldest_page_even_when_terminal_page_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, terminal_empty: bool
) -> None:
    rank = _service(tmp_path)
    calls: list[int] = []

    async def page(
        _self: Any, _game: Any, *, start: int, end: int, **_: Any
    ) -> RankPageResult:
        calls.append(start)
        return RankPageResult(
            [] if terminal_empty and start == PAGE_SIZE else _score_entries(start, end),
            SOURCE_TIME if start == PAGE_SIZE else SOURCE_TIME + 100,
            from_cache=start == 0,
        )

    monkeypatch.setattr(RankService, "fetch_page_result", page)
    result = await rank.fetch_range_result(
        cast("Any", None),
        key=17,
        sub_key=0,
        start=0,
        count=PAGE_SIZE + 1,
        use_cache=True,
    )
    assert calls == [0, PAGE_SIZE]
    assert len(result.items) == (PAGE_SIZE if terminal_empty else PAGE_SIZE + 1)
    assert result.fetched_at == SOURCE_TIME
    assert not result.from_cache


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, -1])
async def test_empty_request_has_no_page_observation(
    tmp_path: Path, count: int
) -> None:
    rank = _service(tmp_path)
    raw = await rank.fetch_range_result(
        cast("Any", None), key=17, sub_key=0, start=0, count=count
    )
    visible = await rank.fetch_visible_range_result(
        cast("Any", None),
        rank_key="成就点数",
        key=17,
        sub_key=0,
        start_rank=1,
        count=count,
    )
    cached = rank.cached_visible_range_result(
        rank_key="成就点数", key=17, sub_key=0, start_rank=1, count=count
    )
    assert cached is not None
    assert cached.from_cache
    for result in (raw, visible, cached):
        assert result.items == []
        assert result.fetched_at is None
    cast("AsyncMock", rank.fetch_online_page).assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("excluded", [False, True])
async def test_cached_window_uses_only_supporting_pages_including_exclusion_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, excluded: bool
) -> None:
    rank = replace(
        _service(tmp_path),
        exclusions=RankExclusionPolicy(
            frozenset((100_000,)) if excluded else frozenset(), {}
        ),
    )
    for start in (0, PAGE_SIZE):
        rank.cache.save(
            key=17,
            sub_key=0,
            start=start,
            end=start + PAGE_SIZE - 1,
            items=_score_entries(start, start + PAGE_SIZE - 1),
            fetched_at=SOURCE_TIME + start,
        )
    result = rank.cached_visible_range_result(
        rank_key="成就点数", key=17, sub_key=0, start_rank=PAGE_SIZE + 1, count=1
    )
    assert result is not None
    assert result.from_cache
    assert result.fetched_at == (SOURCE_TIME if excluded else SOURCE_TIME + PAGE_SIZE)
    assert result.items[0].id == 100_000 + PAGE_SIZE + int(excluded)
    assert (
        rank.cached_visible_range_result(
            rank_key="成就点数", key=17, sub_key=0, start_rank=PAGE_SIZE * 3, count=1
        )
        is None
    )

    async def page(
        _self: Any, _game: Any, *, start: int, end: int, **_: Any
    ) -> RankPageResult:
        return RankPageResult(
            _score_entries(start, end), SOURCE_TIME + start, from_cache=True
        )

    monkeypatch.setattr(RankService, "fetch_page_result", page)
    online = await rank.fetch_visible_range_result(
        cast("Any", None),
        rank_key="成就点数",
        key=17,
        sub_key=0,
        start_rank=PAGE_SIZE + 1,
        count=1,
    )
    assert online == result


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["match", "gap", "below", "empty", "disabled"])
async def test_score_segment_keeps_probe_and_neighbor_times(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    rank = _service(tmp_path)
    calls: list[int] = []

    async def page(
        _self: Any, _game: Any, *, start: int, end: int, **_: Any
    ) -> RankPageResult:
        calls.append(start)
        stamp = SOURCE_TIME + 100
        if start == LIMIT - PAGE_SIZE:
            stamp = SOURCE_TIME
        if kind == "gap" and start == PAGE_SIZE:
            stamp = SOURCE_TIME - 10
        return RankPageResult(
            [] if kind == "empty" else _score_entries(start, end), stamp
        )

    monkeypatch.setattr(RankService, "fetch_page_result", page)
    target = {"match": 150, "gap": 175, "below": 99, "empty": 150, "disabled": 0}[kind]
    result = await rank.fetch_score_segment(
        cast("Any", None),
        key=17,
        sub_key=0,
        title="rank",
        score_name="score",
        target_score=target,
        sample_limit=2,
    )
    if kind == "disabled":
        assert not calls
        assert result.fetched_at is None
        return
    assert calls[0] == LIMIT - PAGE_SIZE
    assert result.fetched_at == (SOURCE_TIME - 10 if kind == "gap" else SOURCE_TIME)
    if kind == "match":
        assert (result.start_rank, result.end_rank, result.total_count) == (21, 40, 20)
        assert [item.rank_index for item in result.items] == [20, 39]
    elif kind == "gap":
        assert result.higher_gap is not None and result.lower_gap is not None
        assert result.higher_gap.end_rank == result.lower_gap.start_rank - 1
    else:
        assert not result.items


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["cache_only", "cached_candidate", "excluded"])
async def test_score_samples_retain_undisplayed_boundary_page_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    rank = _service(tmp_path)
    for start in range(0, 60, PAGE_SIZE):
        rank.cache.save(
            key=17,
            sub_key=0,
            start=start,
            end=start + PAGE_SIZE - 1,
            items=_score_entries(start, start + PAGE_SIZE - 1),
            fetched_at=SOURCE_TIME if start == PAGE_SIZE else SOURCE_TIME + 100,
        )
    if route == "cache_only":
        result = rank.cached_score_segment(
            rank_key=None,
            key=17,
            sub_key=0,
            title="rank",
            score_name="score",
            target_score=150,
            sample_limit=2,
        )
        assert result is not None
        assert [item.rank_index for item in result.items] == [20, 39]
        assert result.fetched_at == SOURCE_TIME
        cast("AsyncMock", rank.fetch_online_page).assert_not_awaited()
        return

    calls: list[int] = []

    async def page(
        _self: Any, _game: Any, *, start: int, end: int, **_: Any
    ) -> RankPageResult:
        calls.append(start)
        return RankPageResult(
            _score_entries(start, end),
            SOURCE_TIME + 10 if start == PAGE_SIZE else SOURCE_TIME + 100,
        )

    monkeypatch.setattr(RankService, "fetch_page_result", page)
    if route == "excluded":
        rank = replace(rank, exclusions=RankExclusionPolicy(frozenset((100_000,)), {}))
    result = await rank.fetch_score_segment(
        cast("Any", None),
        rank_key="成就点数" if route == "excluded" else None,
        key=17,
        sub_key=0,
        title="rank",
        score_name="score",
        target_score=150,
        sample_limit=2,
    )
    assert result.fetched_at == SOURCE_TIME + 10
    assert PAGE_SIZE in calls
    if route == "excluded":
        assert calls[0] == 0
        assert (result.start_rank, result.end_rank) == (20, 39)
    else:
        assert [item.rank_index for item in result.items] == [20, 39]
        assert 0 not in calls


@pytest.mark.parametrize("stamp", [None, 0.0, SOURCE_TIME])
def test_rank_formatters_do_not_invent_observation_time(
    monkeypatch: pytest.MonkeyPatch, stamp: float | None
) -> None:
    def forbidden() -> str:
        pytest.fail("formatter used the current clock")

    monkeypatch.setattr(
        "ironsbot.services.seer.rank_list_formatting.now_text", forbidden
    )
    item = RankScoreSearchItem(id=100_000, nick="player", score=150, rank_index=20)
    spec = GlobalRankSpec("rank", key=17, sub_key=0, unit="score")
    timestamp = timestamp_text(stamp)
    if stamp is None:
        assert timestamp == "未知"
    if stamp == 0:
        assert timestamp == "1970-01-01 08:00:00"
    score = RankScoreSearchResult(
        title="rank",
        score_name="score",
        target_score=150,
        queried=True,
        total_count=1,
        items=[item],
        fetched_at=stamp,
    )
    assert f"截至{timestamp}" in format_global_rank_message(
        spec, [item], timestamp=timestamp
    )
    assert f"截至{timestamp}" in format_global_rank_score_message(
        spec, score, timestamp=timestamp
    )


def _service(tmp_path: Path) -> RankService:
    cache = SqliteRankPageCache(
        tmp_path / "rank.sqlite",
        enabled=True,
        ttl_seconds=CACHE_TTL_SECONDS,
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
@pytest.mark.parametrize("age", [120, CACHE_TTL_SECONDS, CACHE_TTL_SECONDS + 1])
async def test_live_miss_requires_fresh_evidence_but_cache_only_can_use_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, age: int
) -> None:
    monkeypatch.setattr("time.time", lambda: SOURCE_TIME)
    rank = _service(tmp_path)
    stamp = SOURCE_TIME - age
    rank.cache.save_miss(
        key=240,
        sub_key=1,
        user_id=PLAYER_ID,
        searched_limit=LIMIT,
        fetched_at=stamp,
    )
    historical = rank.cached_player_lookup(
        rank_key="群星牌",
        user_id=PLAYER_ID,
        title="rank",
        score_name="score",
        key=240,
        sub_key=1,
    )
    assert historical is not None
    assert historical[1].fetched_at == stamp
    transport = AsyncMock(return_value=[RankEntry(PLAYER_ID, "found", 100)])
    rank = replace(rank, fetch_online_page=transport)
    result = await rank.find_rank(
        cast("Any", None),
        user_id=PLAYER_ID,
        title="rank",
        score_name="score",
        key=240,
        sub_key=1,
    )
    if age <= CACHE_TTL_SECONDS:
        transport.assert_not_awaited()
        assert result.rank is None
        assert result.fetched_at == stamp
    else:
        transport.assert_awaited_once()
        assert result.rank == 1
        assert result.fetched_at == SOURCE_TIME


@pytest.mark.asyncio
async def test_new_cached_position_supersedes_miss_and_is_confirmed_online(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("time.time", lambda: SOURCE_TIME)
    rank = _service(tmp_path)
    rank.cache.save_miss(
        key=240,
        sub_key=1,
        user_id=PLAYER_ID,
        searched_limit=LIMIT,
        fetched_at=SOURCE_TIME - 120,
    )
    rank.cache.save(
        key=240,
        sub_key=1,
        start=0,
        end=0,
        items=[RankEntry(PLAYER_ID, "cached", 100)],
        fetched_at=SOURCE_TIME - 60,
    )
    transport = AsyncMock(
        return_value=[RankEntry(PLAYER_ID, "confirmed", CONFIRMED_SCORE)]
    )
    rank = replace(rank, fetch_online_page=transport)
    result = await rank.find_rank(
        cast("Any", None),
        user_id=PLAYER_ID,
        title="rank",
        score_name="score",
        key=240,
        sub_key=1,
    )
    transport.assert_awaited_once()
    assert result.rank == 1
    assert result.score == CONFIRMED_SCORE
    assert result.fetched_at == SOURCE_TIME


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
@pytest.mark.parametrize(
    "change", ["replacement", "empty", "duplicate", "score", "stable"]
)
async def test_rank_adjustment_requires_player_and_complete_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    rank = replace(
        _service(tmp_path), exclusions=RankExclusionPolicy(frozenset({999_999}), {})
    )
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
        _self: Any, _game: Any, *, start: int, end: int, **_: Any
    ) -> RankPageResult:
        calls.append(start)
        items = [
            RankEntry(
                PLAYER_ID if index == TARGET_INDEX else index, "player", LIMIT - index
            )
            for index in range(start, end + 1)
        ]
        if len(calls) > 1:
            if change == "empty":
                items = []
            elif change == "replacement" and start == PAGE_SIZE:
                items[-1] = RankEntry(999_998, "replacement", LIMIT - TARGET_INDEX)
            elif change == "duplicate" and start == PAGE_SIZE:
                items[0] = RankEntry(0, "duplicate", LIMIT - start)
            elif change == "score" and start == PAGE_SIZE:
                items[-1] = RankEntry(
                    PLAYER_ID, "changed score", LIMIT - TARGET_INDEX - 1
                )
        return RankPageResult(items, SOURCE_TIME + len(calls))

    monkeypatch.setattr(RankService, "fetch_page_result", page)
    result = await rank.find_rank(
        cast("Any", None),
        user_id=PLAYER_ID,
        title="rank",
        score_name="score",
        key=240,
        sub_key=1,
    )
    if change == "stable":
        assert result.rank == TARGET_INDEX + 1
        assert result.failure is None
    else:
        assert result.rank is None
        assert result.failure is not None and "发生变化" in result.failure
        assert result.score == LIMIT - TARGET_INDEX
    assert calls == ([PAGE_SIZE, 0] if change == "empty" else [PAGE_SIZE, 0, PAGE_SIZE])


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
