import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ironsbot.integrations.storage.rank_page_cache import SqliteRankPageCache

MOVED_RANK_INDEX = 100
MOVED_SCORE = 1001
FETCHED_AT = 1_781_234_567.0
CACHED_PAGE_LOOKUP_INDEX = 123
CACHED_PAGE_LOOKUP_SCORE = 977
OVERLAP_LOOKUP_INDEX = 14
OVERLAP_NEW_USER_ID = 2000
MISS_SEARCH_LIMIT = 2_000


@dataclass(frozen=True)
class RankItem:
    id: int
    nick: str
    score: int


def build_cache(path: Path) -> SqliteRankPageCache:
    return SqliteRankPageCache(
        path,
        enabled=True,
        ttl_seconds=3600,
        allow_stale=True,
    )


def test_save_rank_page_deduplicates_user_within_same_rank(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    cache = build_cache(cache_path)

    cache.save(
        key=1,
        sub_key=2,
        start=0,
        end=99,
        items=[RankItem(id=100, nick="旧名", score=999)],
    )
    cache.save(
        key=1,
        sub_key=2,
        start=100,
        end=199,
        items=[RankItem(id=100, nick="新名", score=1001)],
    )

    cached = cache.item(key=1, sub_key=2, user_id=100)
    assert cached is not None
    assert cached.rank_index == MOVED_RANK_INDEX
    assert cached.nick == "新名"
    assert cached.score == MOVED_SCORE

    summaries = cache.summary(key=1, sub_key=2)
    actual = [
        (
            page.start_index,
            page.item_count,
            page.expected_count,
            page.min_score,
            page.max_score,
            page.is_partial,
        )
        for page in summaries
    ]
    assert actual == [
        (0, 0, 100, None, None, True),
        (100, 1, 100, MOVED_SCORE, MOVED_SCORE, True),
    ]


def test_rank_page_cache_uses_player_rank_fact_schema(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    cache = build_cache(cache_path)

    cache.save(
        key=1,
        sub_key=2,
        start=0,
        end=99,
        items=[RankItem(id=100, nick="Alice", score=999)],
    )

    with sqlite3.connect(cache_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "rank_players",
        "rank_pages",
        "player_rank_facts",
        "player_rank_misses",
    } <= tables
    assert "pages" not in tables
    assert "items" not in tables


def test_save_rank_page_replaces_overlapping_ranges(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    cache = build_cache(cache_path)

    cache.save(
        key=1,
        sub_key=2,
        start=0,
        end=99,
        items=[
            RankItem(id=1000 + index, nick=f"Old{index}", score=2000 - index)
            for index in range(100)
        ],
        fetched_at=FETCHED_AT,
    )
    cache.save(
        key=1,
        sub_key=2,
        start=OVERLAP_LOOKUP_INDEX,
        end=OVERLAP_LOOKUP_INDEX,
        items=[RankItem(id=OVERLAP_NEW_USER_ID, nick="New15", score=1999)],
        fetched_at=FETCHED_AT + 60,
    )

    assert cache.item(key=1, sub_key=2, user_id=1014) is None
    assert cache.item(key=1, sub_key=2, user_id=1000) is None

    cached = cache.item_by_index(
        key=1,
        sub_key=2,
        rank_index=OVERLAP_LOOKUP_INDEX,
    )
    assert cached is not None
    assert cached.id == OVERLAP_NEW_USER_ID
    assert cached.rank_index == OVERLAP_LOOKUP_INDEX

    summaries = cache.summary(key=1, sub_key=2)
    assert [(page.start_index, page.end_index) for page in summaries] == [
        (OVERLAP_LOOKUP_INDEX, OVERLAP_LOOKUP_INDEX),
    ]


def test_cached_rank_page_result_preserves_fetched_at(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    cache = build_cache(cache_path)

    cache.save(
        key=1,
        sub_key=2,
        start=0,
        end=0,
        items=[RankItem(id=100, nick="Alice", score=999)],
        fetched_at=FETCHED_AT,
    )

    cached = cache.page(key=1, sub_key=2, start=0, end=0)

    assert cached is not None
    assert cached.fetched_at == FETCHED_AT
    assert cached.items[0].nick == "Alice"


def test_cached_rank_item_by_index_reads_containing_page(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    cache = build_cache(cache_path)

    cache.save(
        key=1,
        sub_key=2,
        start=100,
        end=199,
        items=[
            RankItem(id=100 + index, nick=f"Player{index}", score=1000 - index)
            for index in range(100)
        ],
        fetched_at=FETCHED_AT,
    )

    cached = cache.item_by_index(
        key=1,
        sub_key=2,
        rank_index=CACHED_PAGE_LOOKUP_INDEX,
    )

    assert cached is not None
    assert cached.id == CACHED_PAGE_LOOKUP_INDEX
    assert cached.rank_index == CACHED_PAGE_LOOKUP_INDEX
    assert cached.score == CACHED_PAGE_LOOKUP_SCORE
    assert cached.fetched_at == FETCHED_AT


def test_rank_miss_cache_requires_the_requested_search_coverage(
    tmp_path: Path,
) -> None:
    cache = build_cache(tmp_path / "rank_page_cache.sqlite")
    cache.save_miss(
        key=1,
        sub_key=2,
        user_id=100,
        searched_limit=MISS_SEARCH_LIMIT,
        fetched_at=FETCHED_AT,
    )

    cached = cache.miss(
        key=1,
        sub_key=2,
        user_id=100,
        minimum_limit=MISS_SEARCH_LIMIT,
    )

    assert cached is not None
    assert cached.searched_limit == MISS_SEARCH_LIMIT
    assert cache.miss(
        key=1,
        sub_key=2,
        user_id=100,
        minimum_limit=MISS_SEARCH_LIMIT + 1,
    ) is None
