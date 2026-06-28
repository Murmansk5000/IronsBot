import asyncio
from types import SimpleNamespace

import nonebot
from pytest import MonkeyPatch

ONLINE_LIMIT = 2000
CACHED_RANK = 50000
CACHED_RANK_INDEX = CACHED_RANK - 1
CACHED_SCORE = 12345
LOW_TARGET_SCORE = 99
BINARY_ONLINE_LIMIT = 1000
BINARY_TARGET_INDEX = 250
BINARY_TARGET_RANK = BINARY_TARGET_INDEX + 1
BINARY_TARGET_SCORE = BINARY_ONLINE_LIMIT - BINARY_TARGET_INDEX
DEFAULT_PROBE_LIMIT = 32
TIED_PAGE_SIZE = 10
TIED_PAGE_LIMIT = 3
TIED_PROBE_LIMIT = 12

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


def _patch_rank_config(
    monkeypatch: MonkeyPatch,
    *,
    online_limit: int = ONLINE_LIMIT,
    page_size: int = 100,
    score_search_probe_limit: int = 32,
    score_search_tie_page_limit: int = 5,
) -> None:
    rank_config = SimpleNamespace(
        limit=10000,
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


def test_score_rank_online_lookup_is_capped_by_online_limit(
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

    assert result.searched_limit == ONLINE_LIMIT
    assert requested_indexes
    assert max(requested_indexes) < ONLINE_LIMIT


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
    assert requested_indexes == [ONLINE_LIMIT - 1]


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
        return SimpleNamespace(score=BINARY_ONLINE_LIMIT - index)

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
                score=BINARY_ONLINE_LIMIT - rank_index,
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
    assert max(requested_indexes) < BINARY_ONLINE_LIMIT
    assert len(requested_indexes) <= DEFAULT_PROBE_LIMIT
    assert requested_pages == [(BINARY_TARGET_INDEX, BINARY_TARGET_INDEX)]


def test_score_rank_lookup_limits_tied_score_page_scan(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(
        monkeypatch,
        online_limit=BINARY_ONLINE_LIMIT,
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
        return SimpleNamespace(score=100)

    async def fake_fetch_rank_page(
        *_args: object,
        start: int,
        end: int,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        requested_pages.append((start, end))
        return [
            SimpleNamespace(id=rank_index, score=100)
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
            target_score=100,
        )
    )

    assert result.rank is None
    assert requested_pages == [
        (0, TIED_PAGE_SIZE - 1),
        (TIED_PAGE_SIZE, TIED_PAGE_SIZE * 2 - 1),
        (TIED_PAGE_SIZE * 2, TIED_PAGE_SIZE * TIED_PAGE_LIMIT - 1),
    ]


def test_cached_rank_is_returned_even_when_cache_is_stale(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_rank_config(monkeypatch, online_limit=ONLINE_LIMIT)
    scheduled: list[tuple[int, int, int]] = []
    cached_item = CachedRankLookup(
        id=105023264,
        nick="cached",
        score=CACHED_SCORE,
        rank_index=CACHED_RANK_INDEX,
        fetched_at=0,
        is_stale=True,
    )

    monkeypatch.setattr(_rank, "get_cached_rank_item", lambda **_: cached_item)
    monkeypatch.setattr(
        _rank,
        "_schedule_cached_rank_window_refresh",
        lambda _game, *, key, sub_key, center_index, **_kwargs: scheduled.append(
            (key, sub_key, center_index)
        ),
    )

    async def unexpected_fetch(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    monkeypatch.setattr(_rank, "_fetch_rank_item", unexpected_fetch)

    result = asyncio.run(
        _rank._find_rank(
            object(),
            user_id=105023264,
            title="book",
            score_name="score",
            key=156,
            sub_key=1,
            target_score=100,
        )
    )

    assert result.queried is True
    assert result.rank == CACHED_RANK
    assert result.score == CACHED_SCORE
    assert scheduled == [(156, 1, CACHED_RANK_INDEX)]
