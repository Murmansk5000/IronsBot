import asyncio
from types import SimpleNamespace

import nonebot
from pytest import MonkeyPatch

ONLINE_LIMIT = 2000
CACHED_RANK = 50000
CACHED_RANK_INDEX = CACHED_RANK - 1
CACHED_SCORE = 12345

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()
try:
    nonebot.load_plugin("nonebot_plugin_htmlkit")
except RuntimeError as e:
    if "Plugin already exists" not in str(e):
        raise

from ironsbot.custom_plugins.custom_get_seer_info.commands import _rank
from ironsbot.custom_plugins.custom_get_seer_info.commands._rank_page_cache import (
    CachedRankLookup,
)


def _patch_rank_config(
    monkeypatch: MonkeyPatch,
    *,
    online_limit: int = ONLINE_LIMIT,
) -> None:
    rank_config = SimpleNamespace(
        limit=10000,
        online_limit=online_limit,
        page_size=100,
        page_cache=True,
        page_cache_ttl_seconds=3600,
        allow_stale_cache=True,
        refresh_stale_cache=True,
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
