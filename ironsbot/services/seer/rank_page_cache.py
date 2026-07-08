# SPDX-License-Identifier: GPL-3.0-or-later
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from nonebot.log import logger

from ironsbot.config import get_app_config
from ironsbot.config.models.seer import RankQueryConfig


def get_rank_query_config() -> RankQueryConfig:
    return get_app_config().seer.rank


@dataclass(frozen=True, slots=True)
class CachedRankItem:
    id: int
    nick: str
    score: int


@dataclass(frozen=True, slots=True)
class CachedRankPage:
    items: list[CachedRankItem]
    fetched_at: float


@dataclass(frozen=True, slots=True)
class CachedRankLookup:
    id: int
    nick: str
    score: int
    rank_index: int
    fetched_at: float
    is_stale: bool = False


@dataclass(frozen=True, slots=True)
class CachedRankPageSummary:
    start_index: int
    end_index: int
    item_count: int
    expected_count: int
    fetched_at: float
    min_score: int | None = None
    max_score: int | None = None
    is_stale: bool = False
    is_partial: bool = False


def _cache_path() -> Path:
    return get_rank_query_config().page_cache_path


def _connect() -> sqlite3.Connection:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rank_players (
            user_id INTEGER PRIMARY KEY,
            nick TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rank_pages (
            key INTEGER NOT NULL,
            sub_key INTEGER NOT NULL,
            start_index INTEGER NOT NULL,
            end_index INTEGER NOT NULL,
            page_size INTEGER NOT NULL,
            fetched_at REAL NOT NULL,
            expected_count INTEGER NOT NULL,
            actual_count INTEGER NOT NULL,
            PRIMARY KEY (key, sub_key, start_index, end_index)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS player_rank_facts (
            key INTEGER NOT NULL,
            sub_key INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rank_index INTEGER NOT NULL,
            score INTEGER NOT NULL,
            display TEXT NOT NULL DEFAULT '',
            fetched_at REAL NOT NULL,
            source_start_index INTEGER NOT NULL,
            source_end_index INTEGER NOT NULL,
            PRIMARY KEY (key, sub_key, user_id),
            UNIQUE (key, sub_key, rank_index)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_player_rank_facts_rank
        ON player_rank_facts (key, sub_key, rank_index)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_player_rank_facts_score
        ON player_rank_facts (key, sub_key, score DESC, rank_index)
        """
    )
    return conn


def _is_cache_enabled() -> bool:
    return get_rank_query_config().page_cache


def _is_stale(fetched_at: float) -> bool:
    ttl = get_rank_query_config().page_cache_ttl_seconds
    return ttl <= 0 or time.time() - fetched_at > ttl


def _is_stale_allowed(*, allow_stale: bool | None) -> bool:
    if allow_stale is None:
        return get_rank_query_config().allow_stale_cache
    return allow_stale


def get_cached_rank_page(
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    allow_stale: bool | None = None,
) -> list[CachedRankItem] | None:
    page = get_cached_rank_page_result(
        key=key,
        sub_key=sub_key,
        start=start,
        end=end,
        allow_stale=allow_stale,
    )
    return None if page is None else page.items


def get_cached_rank_page_result(
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    allow_stale: bool | None = None,
) -> CachedRankPage | None:
    if not _is_cache_enabled():
        return None

    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT fetched_at, expected_count
                FROM rank_pages
                WHERE key = ?
                  AND sub_key = ?
                  AND start_index = ?
                  AND end_index = ?
                """,
                (key, sub_key, start, end),
            ).fetchone()
            if row is None:
                return None

            fetched_at, expected_count = row
            fetched_at_float = float(fetched_at)
            if _is_stale(fetched_at_float) and not _is_stale_allowed(
                allow_stale=allow_stale,
            ):
                return None

            rows = conn.execute(
                """
                SELECT
                    f.user_id,
                    COALESCE(NULLIF(f.display, ''), p.nick, '') AS nick,
                    f.score
                FROM player_rank_facts f
                LEFT JOIN rank_players p
                  ON p.user_id = f.user_id
                WHERE f.key = ?
                  AND f.sub_key = ?
                  AND f.rank_index BETWEEN ? AND ?
                ORDER BY f.rank_index
                """,
                (key, sub_key, start, end),
            ).fetchall()
            if len(rows) != int(expected_count):
                return None

            return CachedRankPage(
                items=[
                    CachedRankItem(id=int(user_id), nick=str(nick), score=int(score))
                    for user_id, nick, score in rows
                ],
                fetched_at=fetched_at_float,
            )
    except sqlite3.Error as e:
        logger.warning(f"failed to read Seer rank page cache: {e}")
        return None


def get_cached_rank_item(
    *,
    key: int,
    sub_key: int,
    user_id: int,
    allow_stale: bool | None = None,
) -> CachedRankLookup | None:
    if not _is_cache_enabled():
        return None

    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(f.display, ''), p.nick, '') AS nick,
                    f.score,
                    f.rank_index,
                    f.fetched_at
                FROM player_rank_facts f
                LEFT JOIN rank_players p
                  ON p.user_id = f.user_id
                WHERE f.key = ?
                  AND f.sub_key = ?
                  AND f.user_id = ?
                """,
                (key, sub_key, user_id),
            ).fetchone()
            if row is None:
                return None

            nick, score, rank_index, fetched_at = row
            fetched_at_float = float(fetched_at)
            stale = _is_stale(fetched_at_float)
            if stale and not _is_stale_allowed(allow_stale=allow_stale):
                return None
            return CachedRankLookup(
                id=user_id,
                nick=str(nick),
                score=int(score),
                rank_index=int(rank_index),
                fetched_at=fetched_at_float,
                is_stale=stale,
            )
    except sqlite3.Error as e:
        logger.warning(f"failed to read cached Seer rank item: {e}")
        return None


def get_cached_rank_item_by_index(
    *,
    key: int,
    sub_key: int,
    rank_index: int,
    allow_stale: bool | None = None,
) -> CachedRankLookup | None:
    if not _is_cache_enabled():
        return None

    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT
                    f.user_id,
                    COALESCE(NULLIF(f.display, ''), p.nick, '') AS nick,
                    f.score,
                    f.fetched_at
                FROM player_rank_facts f
                LEFT JOIN rank_players p
                  ON p.user_id = f.user_id
                WHERE f.key = ?
                  AND f.sub_key = ?
                  AND f.rank_index = ?
                """,
                (key, sub_key, rank_index),
            ).fetchone()
            if row is None:
                return None

            user_id, nick, score, fetched_at = row
            fetched_at_float = float(fetched_at)
            stale = _is_stale(fetched_at_float)
            if stale and not _is_stale_allowed(allow_stale=allow_stale):
                return None
            return CachedRankLookup(
                id=int(user_id),
                nick=str(nick),
                score=int(score),
                rank_index=rank_index,
                fetched_at=fetched_at_float,
                is_stale=stale,
            )
    except sqlite3.Error as e:
        logger.warning(f"failed to read cached Seer rank item by index: {e}")
        return None


def get_rank_page_cache_summary(
    *,
    key: int,
    sub_key: int,
) -> list[CachedRankPageSummary]:
    if not _is_cache_enabled():
        return []

    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    p.start_index,
                    p.end_index,
                    p.fetched_at,
                    p.expected_count,
                    COUNT(f.user_id) AS actual_count,
                    MIN(f.score) AS min_score,
                    MAX(f.score) AS max_score
                FROM rank_pages p
                LEFT JOIN player_rank_facts f
                  ON f.key = p.key
                 AND f.sub_key = p.sub_key
                 AND f.rank_index BETWEEN p.start_index AND p.end_index
                WHERE p.key = ?
                  AND p.sub_key = ?
                GROUP BY
                    p.start_index,
                    p.end_index,
                    p.fetched_at,
                    p.expected_count
                ORDER BY p.start_index, p.end_index
                """,
                (key, sub_key),
            ).fetchall()
    except sqlite3.Error as e:
        logger.warning(f"failed to read Seer rank page cache summary: {e}")
        return []

    now = time.time()
    ttl = get_rank_query_config().page_cache_ttl_seconds
    return [
        CachedRankPageSummary(
            start_index=int(start_index),
            end_index=int(end_index),
            item_count=int(actual_count),
            expected_count=int(expected_count),
            fetched_at=float(fetched_at),
            min_score=None if min_score is None else int(min_score),
            max_score=None if max_score is None else int(max_score),
            is_stale=ttl <= 0 or now - float(fetched_at) > ttl,
            is_partial=int(actual_count) < int(expected_count),
        )
        for (
            start_index,
            end_index,
            fetched_at,
            expected_count,
            actual_count,
            min_score,
            max_score,
        ) in rows
    ]


def get_cached_rank_score_indexes(
    *,
    key: int,
    sub_key: int,
    score: int,
    start_index: int,
    end_index: int,
) -> list[int]:
    if not _is_cache_enabled():
        return []

    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT rank_index
                FROM player_rank_facts
                WHERE key = ?
                  AND sub_key = ?
                  AND score = ?
                  AND rank_index >= ?
                  AND rank_index < ?
                ORDER BY rank_index
                """,
                (key, sub_key, score, start_index, end_index),
            ).fetchall()
    except sqlite3.Error as e:
        logger.warning(f"failed to read cached Seer rank score indexes: {e}")
        return []

    return [int(row[0]) for row in rows]


def save_rank_page(  # noqa: PLR0913
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    items: Sequence[object],
    fetched_at: float | None = None,
) -> None:
    if not _is_cache_enabled():
        return

    fetched_at_value = time.time() if fetched_at is None else fetched_at
    normalized_items = [
        (
            start + position,
            int(getattr(item, "id", 0)),
            str(getattr(item, "nick", "")),
            int(getattr(item, "score", 0)),
        )
        for position, item in enumerate(items)
        if int(getattr(item, "id", 0)) > 0
    ]
    user_ids = [user_id for _rank_index, user_id, _nick, _score in normalized_items]
    expected_count = max(0, end - start + 1)
    actual_count = len(
        {user_id for _rank_index, user_id, _nick, _score in normalized_items}
    )

    try:
        with _connect() as conn:
            overlapping_pages = conn.execute(
                """
                SELECT start_index, end_index
                FROM rank_pages
                WHERE key = ?
                  AND sub_key = ?
                  AND NOT (end_index < ? OR start_index > ?)
                """,
                (key, sub_key, start, end),
            ).fetchall()
            for old_start, old_end in overlapping_pages:
                conn.execute(
                    """
                    DELETE FROM player_rank_facts
                    WHERE key = ?
                      AND sub_key = ?
                      AND source_start_index = ?
                      AND source_end_index = ?
                    """,
                    (key, sub_key, old_start, old_end),
                )
                conn.execute(
                    """
                    DELETE FROM rank_pages
                    WHERE key = ?
                      AND sub_key = ?
                      AND start_index = ?
                      AND end_index = ?
                    """,
                    (key, sub_key, old_start, old_end),
                )
            conn.execute(
                """
                DELETE FROM player_rank_facts
                WHERE key = ?
                  AND sub_key = ?
                  AND rank_index BETWEEN ? AND ?
                """,
                (key, sub_key, start, end),
            )
            if user_ids:
                conn.executemany(
                    """
                    DELETE FROM player_rank_facts
                    WHERE key = ?
                      AND sub_key = ?
                      AND user_id = ?
                    """,
                    ((key, sub_key, user_id) for user_id in user_ids),
                )
            conn.execute(
                """
                INSERT INTO rank_pages (
                    key, sub_key, start_index, end_index,
                    page_size, fetched_at, expected_count, actual_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key, sub_key, start_index, end_index) DO UPDATE SET
                    page_size = excluded.page_size,
                    fetched_at = excluded.fetched_at,
                    expected_count = excluded.expected_count,
                    actual_count = excluded.actual_count
                """,
                (
                    key,
                    sub_key,
                    start,
                    end,
                    expected_count,
                    fetched_at_value,
                    expected_count,
                    actual_count,
                ),
            )
            conn.executemany(
                """
                INSERT INTO rank_players (user_id, nick, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    nick = excluded.nick,
                    updated_at = excluded.updated_at
                """,
                [
                    (user_id, nick, fetched_at_value)
                    for _rank_index, user_id, nick, _score in normalized_items
                ],
            )
            conn.executemany(
                """
                INSERT INTO player_rank_facts (
                    key, sub_key, user_id, rank_index, score, display, fetched_at,
                    source_start_index, source_end_index
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key, sub_key, user_id) DO UPDATE SET
                    rank_index = excluded.rank_index,
                    score = excluded.score,
                    display = excluded.display,
                    fetched_at = excluded.fetched_at,
                    source_start_index = excluded.source_start_index,
                    source_end_index = excluded.source_end_index
                """,
                [
                    (
                        key,
                        sub_key,
                        user_id,
                        rank_index,
                        score,
                        nick,
                        fetched_at_value,
                        start,
                        end,
                    )
                    for rank_index, user_id, nick, score in normalized_items
                ],
            )
    except sqlite3.Error as e:
        logger.warning(f"failed to write Seer rank page cache: {e}")
