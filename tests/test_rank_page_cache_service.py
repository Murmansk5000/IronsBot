import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier

import pytest

from ironsbot.integrations.storage import rank_page_cache as storage
from ironsbot.integrations.storage.rank_page_cache import SqliteRankPageCache

MOVED_RANK_INDEX = 100
MOVED_SCORE = 1001
FETCHED_AT = 1_781_234_567.0
CACHED_PAGE_LOOKUP_INDEX = 123
CACHED_PAGE_LOOKUP_SCORE = 977
OVERLAP_LOOKUP_INDEX = 14
OVERLAP_NEW_USER_ID = 2000
MISS_SEARCH_LIMIT = 2_000
CROSS_PAGE_LAST_RANK_INDEX = 4_900
CROSS_PAGE_LAST_SCORE = 999


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


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0, FETCHED_AT + 60])
def test_invalid_observation_cannot_replace_valid_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: float,
) -> None:
    monkeypatch.setattr(storage.time, "time", lambda: FETCHED_AT)
    path = tmp_path / "rank.sqlite"
    cache = build_cache(path)
    cache.save(key=1, sub_key=2, start=0, end=0, items=[RankItem(100, "valid", 999)])
    cache.save(
        key=1,
        sub_key=2,
        start=0,
        end=0,
        items=[RankItem(200, "invalid", 998)],
        fetched_at=invalid,
    )
    cached = build_cache(path).item(key=1, sub_key=2, user_id=100)
    assert cached is not None
    assert cached.fetched_at == FETCHED_AT


@pytest.mark.parametrize("invalid", [float("inf"), -1.0, FETCHED_AT + 60])
def test_invalid_persisted_times_are_not_historical_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: float,
) -> None:
    monkeypatch.setattr(storage.time, "time", lambda: FETCHED_AT)
    path = tmp_path / "rank.sqlite"
    cache = build_cache(path)
    cache.save(key=1, sub_key=2, start=0, end=0, items=[RankItem(100, "valid", 999)])
    cache.save_miss(key=1, sub_key=2, user_id=200, searched_limit=100)
    with sqlite3.connect(path) as conn:
        for table in (
            "rank_pages",
            "player_rank_facts",
            "player_rank_last_seen",
            "player_rank_misses",
        ):
            conn.execute(f"UPDATE {table} SET fetched_at=?", (invalid,))
    cache = build_cache(path)
    assert cache.page(key=1, sub_key=2, start=0, end=0, allow_stale=True) is None
    assert cache.item(key=1, sub_key=2, user_id=100, allow_stale=True) is None
    assert cache.item_by_index(key=1, sub_key=2, rank_index=0, allow_stale=True) is None
    assert (
        cache.last_seen_item(key=1, sub_key=2, user_id=100, max_age_seconds=3600)
        is None
    )
    assert (
        cache.miss(key=1, sub_key=2, user_id=200, minimum_limit=100, allow_stale=True)
        is None
    )
    assert cache.summary(key=1, sub_key=2) == []
    assert (
        cache.score_indexes(key=1, sub_key=2, score=999, start_index=0, end_index=100)
        == []
    )
    cache.save(
        key=1, sub_key=2, start=0, end=0, items=[RankItem(100, "recovered", 998)]
    )
    recovered = build_cache(path).item(key=1, sub_key=2, user_id=100)
    assert recovered is not None
    assert recovered.nick == "recovered"


@pytest.mark.parametrize("invalid", [float("inf"), -1.0, FETCHED_AT + 60])
def test_invalid_positive_does_not_suppress_valid_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: float,
) -> None:
    monkeypatch.setattr(storage.time, "time", lambda: FETCHED_AT)
    path = tmp_path / "rank.sqlite"
    cache = build_cache(path)
    cache.save(key=1, sub_key=2, start=0, end=0, items=[RankItem(100, "valid", 999)])
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE player_rank_last_seen SET fetched_at=?", (invalid,))
    cache.save_miss(key=1, sub_key=2, user_id=100, searched_limit=100)
    assert (
        build_cache(path).miss(key=1, sub_key=2, user_id=100, minimum_limit=100)
        is not None
    )


@pytest.mark.parametrize("invalid", [float("inf"), -1.0, FETCHED_AT + 60])
def test_invalid_fact_cannot_hide_behind_valid_page_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: float,
) -> None:
    monkeypatch.setattr(storage.time, "time", lambda: FETCHED_AT)
    path = tmp_path / "rank.sqlite"
    cache = build_cache(path)
    cache.save(key=1, sub_key=2, start=0, end=0, items=[RankItem(100, "valid", 999)])
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE player_rank_facts SET fetched_at=?", (invalid,))
    assert cache.page(key=1, sub_key=2, start=0, end=0, allow_stale=True) is None
    summary = cache.summary(key=1, sub_key=2)
    assert len(summary) == 1
    assert summary[0].item_count == 0
    assert summary[0].is_partial
    assert summary[0].min_score is None


@pytest.mark.parametrize("invalid", [float("inf"), -1.0, FETCHED_AT + 60])
def test_valid_observation_repairs_invalid_miss_and_nickname(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: float,
) -> None:
    monkeypatch.setattr(storage.time, "time", lambda: FETCHED_AT)
    path = tmp_path / "rank.sqlite"
    cache = build_cache(path)
    cache.save(key=1, sub_key=2, start=0, end=0, items=[RankItem(100, "old", 999)])
    cache.save_miss(key=1, sub_key=2, user_id=200, searched_limit=100)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE player_rank_misses SET fetched_at=?", (invalid,))
        conn.execute("UPDATE rank_players SET updated_at=?", (invalid,))
    cache.save_miss(key=1, sub_key=2, user_id=200, searched_limit=200)
    cache.save(key=1, sub_key=2, start=0, end=0, items=[RankItem(100, "new", 999)])
    miss = build_cache(path).miss(key=1, sub_key=2, user_id=200, minimum_limit=200)
    assert miss is not None
    assert miss.fetched_at == FETCHED_AT
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT nick, updated_at FROM rank_players WHERE user_id=100"
        ).fetchone() == ("new", FETCHED_AT)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0, FETCHED_AT + 60])
def test_invalid_miss_write_preserves_valid_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: float,
) -> None:
    monkeypatch.setattr(storage.time, "time", lambda: FETCHED_AT)
    path = tmp_path / "rank.sqlite"
    cache = build_cache(path)
    searched_limit = 100
    cache.save_miss(key=1, sub_key=2, user_id=100, searched_limit=searched_limit)
    cache.save_miss(
        key=1, sub_key=2, user_id=100, searched_limit=200, fetched_at=invalid
    )
    miss = build_cache(path).miss(key=1, sub_key=2, user_id=100, minimum_limit=100)
    assert miss is not None
    assert miss.searched_limit == searched_limit
    assert miss.fetched_at == FETCHED_AT


@pytest.mark.parametrize("old_start", [0, 100])
def test_late_old_page_cannot_replace_newer_rank_after_reopening(
    tmp_path: Path,
    old_start: int,
) -> None:
    path = tmp_path / "rank.sqlite"
    build_cache(path).save(
        key=1,
        sub_key=2,
        start=0,
        end=99,
        items=[RankItem(100, "new", 1001)],
        fetched_at=FETCHED_AT + 60,
    )
    build_cache(path).save(
        key=1,
        sub_key=2,
        start=old_start,
        end=old_start + 99,
        items=[RankItem(100, "old", 999)],
        fetched_at=FETCHED_AT,
    )
    reopened = build_cache(path)
    current = reopened.item(key=1, sub_key=2, user_id=100)
    assert current is not None
    assert (current.rank_index, current.nick, current.score, current.fetched_at) == (
        0,
        "new",
        1001,
        FETCHED_AT + 60,
    )
    assert len(reopened.summary(key=1, sub_key=2)) == 1


def test_late_empty_page_cannot_erase_newer_page(tmp_path: Path) -> None:
    path = tmp_path / "rank.sqlite"
    build_cache(path).save(
        key=1,
        sub_key=2,
        start=0,
        end=99,
        items=[RankItem(100, "new", 1001)],
        fetched_at=FETCHED_AT + 60,
    )
    build_cache(path).save(
        key=1,
        sub_key=2,
        start=0,
        end=99,
        items=[],
        fetched_at=FETCHED_AT,
    )
    assert build_cache(path).item(key=1, sub_key=2, user_id=100) is not None


@pytest.mark.parametrize("start", [0, MISS_SEARCH_LIMIT])
def test_old_positive_respects_newer_miss_coverage(tmp_path: Path, start: int) -> None:
    path = tmp_path / "rank.sqlite"
    build_cache(path).save_miss(
        key=1,
        sub_key=2,
        user_id=100,
        searched_limit=MISS_SEARCH_LIMIT,
        fetched_at=FETCHED_AT + 60,
    )
    build_cache(path).save(
        key=1,
        sub_key=2,
        start=start,
        end=start + 99,
        items=[RankItem(100, "old", 999)],
        fetched_at=FETCHED_AT,
    )
    cached = build_cache(path).item(key=1, sub_key=2, user_id=100)
    assert (cached is not None) is (start == MISS_SEARCH_LIMIT)


def test_independent_older_page_keeps_newer_global_nickname(tmp_path: Path) -> None:
    path = tmp_path / "rank.sqlite"
    for key, nick, stamp in [(1, "new", FETCHED_AT + 60), (2, "old", FETCHED_AT)]:
        build_cache(path).save(
            key=key,
            sub_key=2,
            start=0,
            end=99,
            items=[RankItem(100, nick, 999)],
            fetched_at=stamp,
        )
    assert build_cache(path).item(key=2, sub_key=2, user_id=100) is not None
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT nick FROM rank_players WHERE user_id=100"
        ).fetchone() == ("new",)


def test_concurrent_page_writers_keep_latest_observation(tmp_path: Path) -> None:
    path = tmp_path / "rank.sqlite"
    build_cache(path).save(key=1, sub_key=2, start=0, end=99, items=[], fetched_at=1)
    barrier = Barrier(2)

    def write(offset: int) -> None:
        barrier.wait(timeout=5)
        build_cache(path).save(
            key=1,
            sub_key=2,
            start=0,
            end=99,
            items=[RankItem(100, str(offset), 999 + offset)],
            fetched_at=FETCHED_AT + offset,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(write, (0, 60)))
    latest = build_cache(path).item(key=1, sub_key=2, user_id=100)
    assert latest is not None
    assert latest.fetched_at == FETCHED_AT + 60


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
        items=[RankItem(id=100, nick="Alice", score=CROSS_PAGE_LAST_SCORE)],
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
        "player_rank_last_seen",
    } <= tables
    assert "pages" not in tables
    assert "items" not in tables


def test_rank_page_cache_migration_backfills_last_seen_from_existing_facts(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    cache = build_cache(cache_path)
    cache.save(
        key=1,
        sub_key=2,
        start=0,
        end=0,
        items=[RankItem(id=100, nick="Alice", score=CROSS_PAGE_LAST_SCORE)],
    )
    with sqlite3.connect(cache_path) as conn:
        conn.execute("DROP TABLE player_rank_last_seen")
        conn.execute("PRAGMA user_version = 2")

    migrated = build_cache(cache_path).last_seen_item(
        key=1,
        sub_key=2,
        user_id=100,
        max_age_seconds=24 * 60 * 60,
    )

    assert migrated is not None
    assert migrated.rank_index == 0
    assert migrated.score == CROSS_PAGE_LAST_SCORE


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


def test_overlapping_page_refresh_keeps_last_confirmed_player_rank(
    tmp_path: Path,
) -> None:
    cache = build_cache(tmp_path / "rank_page_cache.sqlite")
    cache.save(
        key=1,
        sub_key=2,
        start=CROSS_PAGE_LAST_RANK_INDEX,
        end=4_999,
        items=[RankItem(id=100, nick="Alice", score=CROSS_PAGE_LAST_SCORE)],
        fetched_at=FETCHED_AT,
    )
    cache.save(
        key=1,
        sub_key=2,
        start=CROSS_PAGE_LAST_RANK_INDEX,
        end=4_999,
        items=[RankItem(id=200, nick="Bob", score=1_000)],
        fetched_at=FETCHED_AT + 60,
    )

    assert cache.item(key=1, sub_key=2, user_id=100) is None
    cached = cache.last_seen_item(
        key=1,
        sub_key=2,
        user_id=100,
        max_age_seconds=float("inf"),
    )
    assert cached is not None
    assert cached.rank_index == CROSS_PAGE_LAST_RANK_INDEX
    assert cached.score == CROSS_PAGE_LAST_SCORE


def test_confirmed_rank_miss_invalidates_last_seen_rank_inside_search_limit(
    tmp_path: Path,
) -> None:
    cache = build_cache(tmp_path / "rank_page_cache.sqlite")
    cache.save(
        key=1,
        sub_key=2,
        start=0,
        end=0,
        items=[RankItem(id=100, nick="Alice", score=999)],
    )
    cache.save_miss(
        key=1,
        sub_key=2,
        user_id=100,
        searched_limit=100,
    )

    assert cache.last_seen_item(
        key=1,
        sub_key=2,
        user_id=100,
        max_age_seconds=24 * 60 * 60,
    ) is None


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


@pytest.mark.parametrize("miss_first", [True, False])
@pytest.mark.parametrize(
    ("key", "sub_key", "user_id", "index", "offset", "contradicts"),
    [
        (1, 2, 100, 0, 1, True),
        (1, 2, 100, 0, 0, True),
        (1, 2, 100, 0, -1, False),
        (2, 2, 100, 0, 1, False),
        (1, 3, 100, 0, 1, False),
        (1, 2, 101, 0, 1, False),
        (1, 2, 100, MISS_SEARCH_LIMIT, 1, False),
    ],
)
def test_miss_proof_respects_newer_positive_evidence(  # noqa: PLR0913
    tmp_path: Path,
    *,
    miss_first: bool,
    key: int,
    sub_key: int,
    user_id: int,
    index: int,
    offset: int,
    contradicts: bool,
) -> None:
    cache = build_cache(tmp_path / "rank.sqlite")

    def save_miss() -> None:
        cache.save_miss(
            key=1,
            sub_key=2,
            user_id=100,
            searched_limit=MISS_SEARCH_LIMIT,
            fetched_at=FETCHED_AT,
        )

    if miss_first:
        save_miss()
    cache.save(
        key=key,
        sub_key=sub_key,
        start=index,
        end=index,
        items=[RankItem(user_id, "player", 100)],
        fetched_at=FETCHED_AT + offset,
    )
    if not miss_first:
        save_miss()
    proof = cache.miss(key=1, sub_key=2, user_id=100, minimum_limit=MISS_SEARCH_LIMIT)
    assert (proof is None) == contradicts
    if proof is not None:
        assert proof.fetched_at == FETCHED_AT


def test_delayed_miss_does_not_replace_newer_proof(tmp_path: Path) -> None:
    cache = build_cache(tmp_path / "rank.sqlite")
    for stamp, limit in ((FETCHED_AT, MISS_SEARCH_LIMIT), (FETCHED_AT - 1, 100)):
        cache.save_miss(
            key=1,
            sub_key=2,
            user_id=100,
            searched_limit=limit,
            fetched_at=stamp,
        )
    proof = cache.miss(key=1, sub_key=2, user_id=100, minimum_limit=MISS_SEARCH_LIMIT)
    assert proof is not None
    assert proof.fetched_at == FETCHED_AT
