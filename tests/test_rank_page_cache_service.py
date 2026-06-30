from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

from ironsbot.services.seer import rank_page_cache
from ironsbot.services.seer.rank_page_cache import (
    get_cached_rank_item,
    get_cached_rank_item_by_index,
    get_cached_rank_page_result,
    get_rank_page_cache_summary,
    save_rank_page,
)

MOVED_RANK_INDEX = 100
MOVED_SCORE = 1001
FETCHED_AT = 1_781_234_567.0
CACHED_PAGE_LOOKUP_INDEX = 123
CACHED_PAGE_LOOKUP_SCORE = 977
OVERLAP_LOOKUP_INDEX = 14
OVERLAP_NEW_USER_ID = 2000


def test_save_rank_page_deduplicates_user_within_same_rank(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    monkeypatch.setattr(
        rank_page_cache,
        "get_rank_query_config",
        lambda: SimpleNamespace(
            page_cache=True,
            page_cache_path=cache_path,
            page_cache_ttl_seconds=3600,
            allow_stale_cache=True,
        ),
    )

    save_rank_page(
        key=1,
        sub_key=2,
        start=0,
        end=99,
        items=[SimpleNamespace(id=100, nick="旧名", score=999)],
    )
    save_rank_page(
        key=1,
        sub_key=2,
        start=100,
        end=199,
        items=[SimpleNamespace(id=100, nick="新名", score=1001)],
    )

    cached = get_cached_rank_item(key=1, sub_key=2, user_id=100)
    assert cached is not None
    assert cached.rank_index == MOVED_RANK_INDEX
    assert cached.nick == "新名"
    assert cached.score == MOVED_SCORE

    summaries = get_rank_page_cache_summary(key=1, sub_key=2)
    actual = [
        (page.start_index, page.item_count, page.expected_count, page.is_partial)
        for page in summaries
    ]
    assert actual == [
        (0, 0, 1, True),
        (100, 1, 1, False),
    ]


def test_save_rank_page_replaces_overlapping_ranges(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    monkeypatch.setattr(
        rank_page_cache,
        "get_rank_query_config",
        lambda: SimpleNamespace(
            page_cache=True,
            page_cache_path=cache_path,
            page_cache_ttl_seconds=3600,
            allow_stale_cache=True,
        ),
    )

    save_rank_page(
        key=1,
        sub_key=2,
        start=0,
        end=99,
        items=[
            SimpleNamespace(id=1000 + index, nick=f"Old{index}", score=2000 - index)
            for index in range(100)
        ],
        fetched_at=FETCHED_AT,
    )
    save_rank_page(
        key=1,
        sub_key=2,
        start=OVERLAP_LOOKUP_INDEX,
        end=OVERLAP_LOOKUP_INDEX,
        items=[SimpleNamespace(id=OVERLAP_NEW_USER_ID, nick="New15", score=1999)],
        fetched_at=FETCHED_AT + 60,
    )

    assert get_cached_rank_item(key=1, sub_key=2, user_id=1014) is None

    cached = get_cached_rank_item_by_index(
        key=1,
        sub_key=2,
        rank_index=OVERLAP_LOOKUP_INDEX,
    )
    assert cached is not None
    assert cached.id == OVERLAP_NEW_USER_ID
    assert cached.rank_index == OVERLAP_LOOKUP_INDEX


def test_cached_rank_page_result_preserves_fetched_at(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    monkeypatch.setattr(
        rank_page_cache,
        "get_rank_query_config",
        lambda: SimpleNamespace(
            page_cache=True,
            page_cache_path=cache_path,
            page_cache_ttl_seconds=3600,
            allow_stale_cache=True,
        ),
    )

    save_rank_page(
        key=1,
        sub_key=2,
        start=0,
        end=0,
        items=[SimpleNamespace(id=100, nick="Alice", score=999)],
        fetched_at=FETCHED_AT,
    )

    cached = get_cached_rank_page_result(key=1, sub_key=2, start=0, end=0)

    assert cached is not None
    assert cached.fetched_at == FETCHED_AT
    assert cached.items[0].nick == "Alice"


def test_cached_rank_item_by_index_reads_containing_page(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    monkeypatch.setattr(
        rank_page_cache,
        "get_rank_query_config",
        lambda: SimpleNamespace(
            page_cache=True,
            page_cache_path=cache_path,
            page_cache_ttl_seconds=3600,
            allow_stale_cache=True,
        ),
    )

    save_rank_page(
        key=1,
        sub_key=2,
        start=100,
        end=199,
        items=[
            SimpleNamespace(id=100 + index, nick=f"Player{index}", score=1000 - index)
            for index in range(100)
        ],
        fetched_at=FETCHED_AT,
    )

    cached = get_cached_rank_item_by_index(
        key=1,
        sub_key=2,
        rank_index=CACHED_PAGE_LOOKUP_INDEX,
    )

    assert cached is not None
    assert cached.id == CACHED_PAGE_LOOKUP_INDEX
    assert cached.rank_index == CACHED_PAGE_LOOKUP_INDEX
    assert cached.score == CACHED_PAGE_LOOKUP_SCORE
    assert cached.fetched_at == FETCHED_AT
