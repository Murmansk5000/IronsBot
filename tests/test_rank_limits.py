import asyncio
from types import SimpleNamespace

import nonebot
from pytest import MonkeyPatch

ONLINE_LIMIT = 2000
RANK_LIMIT = 10000
CACHED_RANK = 50000
CACHED_RANK_INDEX = CACHED_RANK - 1
CACHED_SCORE = 12345
LOW_TARGET_SCORE = 99
BINARY_ONLINE_LIMIT = 1000
BINARY_TARGET_INDEX = 250
BINARY_TARGET_RANK = BINARY_TARGET_INDEX + 1
BINARY_TARGET_SCORE = RANK_LIMIT - BINARY_TARGET_INDEX
DEFAULT_PROBE_LIMIT = 32
TIED_PAGE_SIZE = 10
TIED_PAGE_LIMIT = 3
TIED_PROBE_LIMIT = 12
TIED_SCORE = 100
SEGMENT_SCORE = 150
SEGMENT_START_INDEX = 20
SEGMENT_END_INDEX = 45
SEGMENT_START_RANK = SEGMENT_START_INDEX + 1
SEGMENT_COUNT = SEGMENT_END_INDEX - SEGMENT_START_INDEX
SEGMENT_BOUNDARY_SCORE = 100
CACHED_HINT_SEGMENT_START_INDEX = 23
CACHED_HINT_SEGMENT_END_INDEX = 43
CACHED_HINT_SEGMENT_START_RANK = CACHED_HINT_SEGMENT_START_INDEX + 1
CACHED_HINT_SEGMENT_COUNT = (
    CACHED_HINT_SEGMENT_END_INDEX - CACHED_HINT_SEGMENT_START_INDEX
)
CACHED_GAP_TARGET_SCORE = 10000
CACHED_GAP_UPPER_SCORE = 10001
CACHED_GAP_LOWER_SCORE = 9970
FETCHED_AT = 1_781_234_567.0
LOOKUP_INDEX = 14

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()
try:
    nonebot.load_plugin("nonebot_plugin_htmlkit")
except RuntimeError as e:
    if "Plugin already exists" not in str(e):
        raise

from ironsbot.services.seer import rank as _rank
from ironsbot.services.seer.rank_page_cache import (
    CachedRankLookup,
)


def _patch_rank_config(  # noqa: PLR0913
    monkeypatch: MonkeyPatch,
    *,
    online_limit: int = ONLINE_LIMIT,
    rank_limit: int = RANK_LIMIT,
    page_size: int = 100,
    score_search_probe_limit: int = 32,
    score_search_tie_page_limit: int = 5,
) -> None:
    rank_config = SimpleNamespace(
        limit=rank_limit,
        online_limit=online_limit,
        page_size=page_size,
        page_cache=True,
        page_cache_ttl_seconds=3600,
        allow_stale_cache=True,
        refresh_stale_cache=True,
        score_search_probe_limit=score_search_probe_limit,
        score_search_tie_page_limit=score_search_tie_page_limit,
        peak_subkey=None,
    )
    local_rank_config = SimpleNamespace(refresh_interval_seconds=0)
    monkeypatch.setattr(
        _rank,
        "get_rank_query_config",
        lambda: rank_config,
    )
    monkeypatch.setattr(
        _rank,
        "get_local_rank_config",
        lambda: local_rank_config,
    )
    monkeypatch.setattr(
        _rank,
        "get_rank_page_cache_summary",
        lambda **_: [],
    )
    monkeypatch.setattr(
        _rank,
        "get_cached_rank_score_indexes",
        lambda **_: [],
    )


def test_score_rank_lookup_uses_rank_limit_not_online_limit(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(monkeypatch, online_limit=ONLINE_LIMIT)
    requested_indexes: list[int] = []

    monkeypatch.setattr(_rank, "get_cached_rank_item", lambda **_: None)

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> SimpleNamespace:
        requested_indexes.append(index)
        return SimpleNamespace(score=0)

    monkeypatch.setattr(_rank, "_fetch_rank_item", fake_fetch_rank_item)

    result = asyncio.run(
        _rank._find_rank(
            object(),
            user_id=105023264,
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=100,
        )
    )

    assert result.searched_limit == RANK_LIMIT
    assert requested_indexes
    assert max(requested_indexes) == RANK_LIMIT - 1
    assert max(requested_indexes) >= ONLINE_LIMIT


def test_rank_lookup_without_score_uses_online_limit_for_linear_scan(
    monkeypatch: MonkeyPatch,
) -> None:
    online_limit = 250
    page_size = 100
    _patch_rank_config(monkeypatch, online_limit=online_limit, page_size=page_size)
    requested_pages: list[tuple[int, int]] = []

    monkeypatch.setattr(_rank, "get_cached_rank_item", lambda **_: None)

    async def fake_fetch_rank_page(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        requested_pages.append((start, end))
        return [
            SimpleNamespace(id=rank_index, score=online_limit - rank_index)
            for rank_index in range(start, end + 1)
        ]

    monkeypatch.setattr(_rank, "_fetch_rank_page", fake_fetch_rank_page)

    result = asyncio.run(
        _rank._find_rank(
            object(),
            user_id=105023264,
            title="autocard",
            score_name="score",
            key=240,
            sub_key=1,
        )
    )

    assert result.rank is None
    assert result.searched_limit == online_limit
    assert requested_pages == [(0, 99), (100, 199), (200, 249)]


def test_score_rank_lookup_rejects_target_below_boundary(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(monkeypatch, online_limit=ONLINE_LIMIT)
    requested_indexes: list[int] = []

    monkeypatch.setattr(_rank, "get_cached_rank_item", lambda **_: None)

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> SimpleNamespace:
        requested_indexes.append(index)
        return SimpleNamespace(score=100)

    monkeypatch.setattr(_rank, "_fetch_rank_item", fake_fetch_rank_item)

    result = asyncio.run(
        _rank._find_rank(
            object(),
            user_id=105023264,
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=LOW_TARGET_SCORE,
        )
    )

    assert result.rank is None
    assert result.score == LOW_TARGET_SCORE
    assert requested_indexes == [RANK_LIMIT - 1]


def test_score_rank_lookup_finds_rank_with_binary_search(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(monkeypatch, online_limit=BINARY_ONLINE_LIMIT)
    requested_indexes: list[int] = []
    requested_pages: list[tuple[int, int]] = []

    monkeypatch.setattr(_rank, "get_cached_rank_item", lambda **_: None)

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> SimpleNamespace:
        requested_indexes.append(index)
        return SimpleNamespace(score=RANK_LIMIT - index)

    async def fake_fetch_rank_page(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        requested_pages.append((start, end))
        return [
            SimpleNamespace(
                id=105023264 if rank_index == BINARY_TARGET_INDEX else rank_index,
                score=RANK_LIMIT - rank_index,
            )
            for rank_index in range(start, end + 1)
        ]

    monkeypatch.setattr(_rank, "_fetch_rank_item", fake_fetch_rank_item)
    monkeypatch.setattr(_rank, "_fetch_rank_page", fake_fetch_rank_page)

    result = asyncio.run(
        _rank._find_rank(
            object(),
            user_id=105023264,
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=BINARY_TARGET_SCORE,
        )
    )

    assert result.rank == BINARY_TARGET_RANK
    assert result.score == BINARY_TARGET_SCORE
    assert max(requested_indexes) == RANK_LIMIT - 1
    assert len(requested_indexes) <= DEFAULT_PROBE_LIMIT
    assert requested_pages == [(BINARY_TARGET_INDEX, BINARY_TARGET_INDEX)]


def test_score_rank_lookup_limits_tied_score_page_scan(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(
        monkeypatch,
        online_limit=BINARY_ONLINE_LIMIT,
        rank_limit=BINARY_ONLINE_LIMIT,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=TIED_PROBE_LIMIT,
        score_search_tie_page_limit=TIED_PAGE_LIMIT,
    )
    requested_pages: list[tuple[int, int]] = []

    monkeypatch.setattr(_rank, "get_cached_rank_item", lambda **_: None)

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,  # noqa: ARG001
        **_kwargs: object,
    ) -> SimpleNamespace:
        return SimpleNamespace(score=TIED_SCORE)

    async def fake_fetch_rank_page(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        requested_pages.append((start, end))
        return [
            SimpleNamespace(id=rank_index, score=TIED_SCORE)
            for rank_index in range(start, end + 1)
        ]

    monkeypatch.setattr(_rank, "_fetch_rank_item", fake_fetch_rank_item)
    monkeypatch.setattr(_rank, "_fetch_rank_page", fake_fetch_rank_page)

    result = asyncio.run(
        _rank._find_rank(
            object(),
            user_id=105023264,
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=TIED_SCORE,
        )
    )

    assert result.rank is None
    assert requested_pages == [
        (0, TIED_PAGE_SIZE - 1),
        (TIED_PAGE_SIZE, TIED_PAGE_SIZE * 2 - 1),
        (TIED_PAGE_SIZE * 2, TIED_PAGE_SIZE * TIED_PAGE_LIMIT - 1),
    ]


def test_fetch_rank_score_segment_uses_binary_search_and_fetches_tie_pages(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(
        monkeypatch,
        online_limit=100,
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )
    requested_pages: list[tuple[int, int]] = []
    probe_use_cache_values: list[bool] = []
    page_use_cache_values: list[bool] = []

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        use_cache: bool = True,
        **_kwargs: object,
    ) -> SimpleNamespace:
        probe_use_cache_values.append(use_cache)
        if index < SEGMENT_START_INDEX:
            score = 200
        elif index < SEGMENT_END_INDEX:
            score = SEGMENT_SCORE
        else:
            score = SEGMENT_BOUNDARY_SCORE
        return SimpleNamespace(id=index, nick=f"Player{index}", score=score)

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        use_cache: bool = True,
        **_kwargs: object,
    ) -> _rank.RankPageResult:
        requested_pages.append((start, end))
        page_use_cache_values.append(use_cache)
        items = []
        for rank_index in range(start, end + 1):
            if rank_index < SEGMENT_START_INDEX:
                score = 200
            elif rank_index < SEGMENT_END_INDEX:
                score = SEGMENT_SCORE
            else:
                score = SEGMENT_BOUNDARY_SCORE
            items.append(
                SimpleNamespace(
                    id=rank_index,
                    nick=f"Player{rank_index}",
                    score=score,
                )
            )
        return _rank.RankPageResult(items=items, fetched_at=FETCHED_AT)

    monkeypatch.setattr(_rank, "_fetch_rank_item", fake_fetch_rank_item)
    monkeypatch.setattr(_rank, "_fetch_rank_page_result", fake_fetch_rank_page_result)

    result = asyncio.run(
        _rank.fetch_rank_score_segment(
            object(),
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=SEGMENT_SCORE,
        )
    )

    assert result.start_rank == SEGMENT_START_RANK
    assert result.end_rank == SEGMENT_END_INDEX
    assert result.total_count == SEGMENT_COUNT
    assert result.scanned_count == SEGMENT_COUNT
    assert [item.id for item in result.items] == list(
        range(SEGMENT_START_INDEX, SEGMENT_END_INDEX)
    )
    assert probe_use_cache_values
    assert all(use_cache is False for use_cache in probe_use_cache_values)
    assert page_use_cache_values == [False, False, False]
    assert requested_pages == [(20, 29), (30, 39), (40, 49)]


def test_fetch_rank_score_segment_uses_cached_score_bounds_as_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(
        monkeypatch,
        online_limit=100,
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )
    requested_pages: list[tuple[int, int]] = []
    page_use_cache_values: list[bool] = []

    monkeypatch.setattr(
        _rank,
        "get_rank_page_cache_summary",
        lambda **_: [
            SimpleNamespace(start_index=20, end_index=29, min_score=150, max_score=200),
            SimpleNamespace(start_index=30, end_index=39, min_score=150, max_score=150),
            SimpleNamespace(start_index=40, end_index=49, min_score=100, max_score=150),
        ],
    )

    async def unexpected_fetch_rank_item(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        use_cache: bool = True,
        **_kwargs: object,
    ) -> _rank.RankPageResult:
        requested_pages.append((start, end))
        page_use_cache_values.append(use_cache)
        items = []
        for rank_index in range(start, end + 1):
            if rank_index < CACHED_HINT_SEGMENT_START_INDEX:
                score = 200
            elif rank_index < CACHED_HINT_SEGMENT_END_INDEX:
                score = SEGMENT_SCORE
            else:
                score = SEGMENT_BOUNDARY_SCORE
            items.append(
                SimpleNamespace(
                    id=rank_index,
                    nick=f"Player{rank_index}",
                    score=score,
                )
            )
        return _rank.RankPageResult(items=items, fetched_at=FETCHED_AT)

    monkeypatch.setattr(_rank, "_fetch_rank_item", unexpected_fetch_rank_item)
    monkeypatch.setattr(_rank, "_fetch_rank_page_result", fake_fetch_rank_page_result)

    result = asyncio.run(
        _rank.fetch_rank_score_segment(
            object(),
            title="mount",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=SEGMENT_SCORE,
        )
    )

    assert requested_pages == [(20, 29), (30, 39), (40, 49)]
    assert page_use_cache_values == [False, False, False]
    assert result.start_rank == CACHED_HINT_SEGMENT_START_RANK
    assert result.end_rank == CACHED_HINT_SEGMENT_END_INDEX
    assert result.total_count == CACHED_HINT_SEGMENT_COUNT
    assert result.scanned_count == CACHED_HINT_SEGMENT_COUNT
    assert [item.id for item in result.items] == list(
        range(CACHED_HINT_SEGMENT_START_INDEX, CACHED_HINT_SEGMENT_END_INDEX)
    )


def test_fetch_rank_score_segment_uses_cached_score_facts_as_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(
        monkeypatch,
        online_limit=100,
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )
    requested_pages: list[tuple[int, int]] = []

    monkeypatch.setattr(
        _rank,
        "get_cached_rank_score_indexes",
        lambda **_: [SEGMENT_START_INDEX],
    )

    async def unexpected_fetch_rank_item(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> _rank.RankPageResult:
        requested_pages.append((start, end))
        items = []
        for rank_index in range(start, end + 1):
            score = SEGMENT_SCORE if rank_index == SEGMENT_START_INDEX else 200
            items.append(
                SimpleNamespace(
                    id=rank_index,
                    nick=f"Player{rank_index}",
                    score=score,
                )
            )
        return _rank.RankPageResult(items=items, fetched_at=FETCHED_AT)

    monkeypatch.setattr(_rank, "_fetch_rank_item", unexpected_fetch_rank_item)
    monkeypatch.setattr(_rank, "_fetch_rank_page_result", fake_fetch_rank_page_result)

    result = asyncio.run(
        _rank.fetch_rank_score_segment(
            object(),
            title="book",
            score_name="score",
            key=156,
            sub_key=1,
            target_score=SEGMENT_SCORE,
        )
    )

    assert requested_pages == [(20, 29), (10, 19)]
    assert result.start_rank == SEGMENT_START_RANK
    assert result.end_rank == SEGMENT_START_RANK
    assert result.total_count == 1
    assert [item.id for item in result.items] == [SEGMENT_START_INDEX]


def test_fetch_rank_score_segment_uses_complete_cached_page_to_prove_missing_score(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(
        monkeypatch,
        online_limit=100,
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )

    monkeypatch.setattr(
        _rank,
        "get_rank_page_cache_summary",
        lambda **_: [
            SimpleNamespace(
                start_index=50,
                end_index=59,
                item_count=10,
                expected_count=10,
                min_score=CACHED_GAP_LOWER_SCORE,
                max_score=CACHED_GAP_UPPER_SCORE,
                fetched_at=FETCHED_AT,
                is_stale=False,
                is_partial=False,
            )
        ],
    )
    monkeypatch.setattr(_rank, "get_cached_rank_score_indexes", lambda **_: [])

    async def unexpected_fetch_rank_item(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    async def unexpected_fetch_rank_page_result(
        *_args: object,
        **_kwargs: object,
    ) -> None:
        raise AssertionError

    monkeypatch.setattr(_rank, "_fetch_rank_item", unexpected_fetch_rank_item)
    monkeypatch.setattr(
        _rank,
        "_fetch_rank_page_result",
        unexpected_fetch_rank_page_result,
    )

    result = asyncio.run(
        _rank.fetch_rank_score_segment(
            object(),
            title="autocard",
            score_name="score",
            key=240,
            sub_key=1,
            target_score=CACHED_GAP_TARGET_SCORE,
        )
    )

    assert result.items == []
    assert result.boundary_score == CACHED_GAP_LOWER_SCORE
    assert result.fetched_at == FETCHED_AT


def test_fetch_rank_score_segment_rejects_score_below_boundary(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(monkeypatch, rank_limit=100)
    requested_indexes: list[int] = []

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> SimpleNamespace:
        requested_indexes.append(index)
        return SimpleNamespace(
            id=index,
            nick=f"Player{index}",
            score=SEGMENT_BOUNDARY_SCORE,
        )

    monkeypatch.setattr(_rank, "_fetch_rank_item", fake_fetch_rank_item)

    result = asyncio.run(
        _rank.fetch_rank_score_segment(
            object(),
            title="achievement",
            score_name="score",
            key=17,
            sub_key=0,
            target_score=99,
        )
    )

    assert result.boundary_score == SEGMENT_BOUNDARY_SCORE
    assert result.items == []
    assert requested_indexes == [99]


def test_fetch_rank_score_segment_handles_short_rank_board(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(
        monkeypatch,
        rank_limit=100,
        page_size=TIED_PAGE_SIZE,
        score_search_probe_limit=20,
        score_search_tie_page_limit=5,
    )
    actual_count = 60

    async def fake_fetch_rank_item(
        *_args: object,
        index: int,
        **_kwargs: object,
    ) -> SimpleNamespace | None:
        if index >= actual_count:
            return None
        if index < SEGMENT_START_INDEX:
            score = 200
        elif index < SEGMENT_END_INDEX:
            score = SEGMENT_SCORE
        else:
            score = SEGMENT_BOUNDARY_SCORE
        return SimpleNamespace(id=index, nick=f"Player{index}", score=score)

    async def fake_fetch_rank_page_result(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> _rank.RankPageResult:
        items = []
        for rank_index in range(start, min(end + 1, actual_count)):
            if rank_index < SEGMENT_START_INDEX:
                score = 200
            elif rank_index < SEGMENT_END_INDEX:
                score = SEGMENT_SCORE
            else:
                score = SEGMENT_BOUNDARY_SCORE
            items.append(
                SimpleNamespace(
                    id=rank_index,
                    nick=f"Player{rank_index}",
                    score=score,
                )
            )
        return _rank.RankPageResult(items=items, fetched_at=FETCHED_AT)

    monkeypatch.setattr(_rank, "_fetch_rank_item", fake_fetch_rank_item)
    monkeypatch.setattr(_rank, "_fetch_rank_page_result", fake_fetch_rank_page_result)

    result = asyncio.run(
        _rank.fetch_rank_score_segment(
            object(),
            title="book",
            score_name="score",
            key=156,
            sub_key=1,
            target_score=SEGMENT_SCORE,
        )
    )

    assert result.boundary_score == SEGMENT_BOUNDARY_SCORE
    assert result.searched_limit == actual_count
    assert result.start_rank == SEGMENT_START_RANK
    assert result.end_rank == SEGMENT_END_INDEX
    assert result.total_count == SEGMENT_COUNT
    assert [item.id for item in result.items] == list(
        range(SEGMENT_START_INDEX, SEGMENT_END_INDEX)
    )


def test_fresh_cached_rank_is_verified_online_when_score_matches(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(monkeypatch, online_limit=ONLINE_LIMIT, page_size=100)
    requested_ranges: list[tuple[int, int]] = []
    cached_item = CachedRankLookup(
        id=105023264,
        nick="cached",
        score=CACHED_SCORE,
        rank_index=LOOKUP_INDEX,
        fetched_at=FETCHED_AT,
        is_stale=False,
    )

    monkeypatch.setattr(_rank, "get_cached_rank_item", lambda **_: cached_item)

    async def fake_fetch_rank_page(
        _game: object,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = True,
    ) -> list[SimpleNamespace]:
        _ = (key, sub_key)
        requested_ranges.append((start, end))
        assert use_cache is False
        return [
            SimpleNamespace(id=105023264, nick="fresh", score=CACHED_SCORE + 1),
        ]

    monkeypatch.setattr(_rank, "_fetch_rank_page", fake_fetch_rank_page)

    result = asyncio.run(
        _rank._find_rank(
            object(),
            user_id=105023264,
            title="book",
            score_name="score",
            key=156,
            sub_key=1,
            target_score=CACHED_SCORE,
        )
    )

    assert result.queried is True
    assert requested_ranges == [(0, 99)]
    assert result.rank == 1
    assert result.score == CACHED_SCORE + 1


def test_cached_rank_without_target_score_is_verified_nearby(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(monkeypatch, online_limit=ONLINE_LIMIT, page_size=100)
    requested_ranges: list[tuple[int, int]] = []
    cached_item = CachedRankLookup(
        id=105023264,
        nick="cached",
        score=CACHED_SCORE,
        rank_index=LOOKUP_INDEX,
        fetched_at=FETCHED_AT,
        is_stale=False,
    )

    monkeypatch.setattr(_rank, "get_cached_rank_item", lambda **_: cached_item)

    async def fake_fetch_rank_page(
        _game: object,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = True,
    ) -> list[SimpleNamespace]:
        _ = (key, sub_key, use_cache)
        requested_ranges.append((start, end))
        return [
            SimpleNamespace(id=105023264, nick="fresh", score=CACHED_SCORE + 1),
        ]

    monkeypatch.setattr(_rank, "_fetch_rank_page", fake_fetch_rank_page)

    result = asyncio.run(
        _rank._find_rank(
            object(),
            user_id=105023264,
            title="autocard",
            score_name="score",
            key=156,
            sub_key=1,
        )
    )

    assert requested_ranges == [(0, 99)]
    assert result.rank == 1
    assert result.score == CACHED_SCORE + 1


def test_fetch_rank_item_fetches_aligned_page_on_cache_miss(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(monkeypatch, page_size=100)
    requested_ranges: list[tuple[int, int]] = []

    monkeypatch.setattr(_rank, "get_cached_rank_item_by_index", lambda **_: None)
    monkeypatch.setattr(_rank, "save_rank_page", lambda **_: None)

    class FakeGame:
        async def send_and_wait(
            self,
            *_args: object,
            **_kwargs: object,
        ) -> tuple[None, SimpleNamespace]:
            param = _args[1]
            requested_ranges.append((param.start, param.end))
            return None, SimpleNamespace(
                rank_list=[
                    SimpleNamespace(id=index, nick=f"Player{index}", score=1000 - index)
                    for index in range(param.start, param.end + 1)
                ]
            )

    item = asyncio.run(
        _rank._fetch_rank_item(FakeGame(), key=1, sub_key=2, index=LOOKUP_INDEX)
    )

    assert requested_ranges == [(0, 99)]
    assert item is not None
    assert item.id == LOOKUP_INDEX


def test_daily_rank_page_result_fetches_aligned_page_and_slices(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(monkeypatch, page_size=100)
    requested_ranges: list[tuple[int, int]] = []

    async def fake_fetch_rank_page_result(
        _game: object,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        use_cache: bool = True,
    ) -> _rank.RankPageResult:
        _ = (key, sub_key, use_cache)
        requested_ranges.append((start, end))
        return _rank.RankPageResult(
            items=[
                SimpleNamespace(id=index, nick=f"Player{index}", score=1000 - index)
                for index in range(start, end + 1)
            ],
            fetched_at=FETCHED_AT,
        )

    monkeypatch.setattr(_rank, "_fetch_rank_page_result", fake_fetch_rank_page_result)

    result = asyncio.run(
        _rank.fetch_daily_rank_page_result(
            object(),
            key=1,
            sub_key=2,
            start=LOOKUP_INDEX,
            count=1,
        )
    )

    assert requested_ranges == [(0, 99)]
    assert [item.id for item in result.items] == [LOOKUP_INDEX]
    assert result.fetched_at == FETCHED_AT
