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
        CREATE TABLE IF NOT EXISTS pages (
            key INTEGER NOT NULL,
            sub_key INTEGER NOT NULL,
            start_index INTEGER NOT NULL,
            end_index INTEGER NOT NULL,
            fetched_at REAL NOT NULL,
            item_count INTEGER NOT NULL,
            PRIMARY KEY (key, sub_key, start_index, end_index)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            key INTEGER NOT NULL,
            sub_key INTEGER NOT NULL,
            start_index INTEGER NOT NULL,
            end_index INTEGER NOT NULL,
            position INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nick TEXT NOT NULL,
            score INTEGER NOT NULL,
            PRIMARY KEY (key, sub_key, start_index, end_index, position)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rank_page_items
        ON items (key, sub_key, start_index, end_index, position)
        """
    )
    return conn


def _is_cache_enabled() -> bool:
    return get_rank_query_config().page_cache


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
                SELECT fetched_at, item_count
                FROM pages
                WHERE key = ?
                  AND sub_key = ?
                  AND start_index = ?
                  AND end_index = ?
                """,
                (key, sub_key, start, end),
            ).fetchone()
            if row is None:
                return None

            fetched_at, item_count = row
            rank_config = get_rank_query_config()
            ttl = rank_config.page_cache_ttl_seconds
            is_stale = ttl <= 0 or time.time() - float(fetched_at) > ttl
            stale_allowed = (
                rank_config.allow_stale_cache
                if allow_stale is None
                else allow_stale
            )
            if is_stale and not stale_allowed:
                return None

            rows = conn.execute(
                """
                SELECT user_id, nick, score
                FROM items
                WHERE key = ?
                  AND sub_key = ?
                  AND start_index = ?
                  AND end_index = ?
                ORDER BY position
                """,
                (key, sub_key, start, end),
            ).fetchall()
            if len(rows) != int(item_count):
                return None

            return CachedRankPage(
                items=[
                    CachedRankItem(id=int(user_id), nick=str(nick), score=int(score))
                    for user_id, nick, score in rows
                ],
                fetched_at=float(fetched_at),
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
                    i.nick,
                    i.score,
                    i.start_index,
                    i.position,
                    p.fetched_at
                FROM items i
                JOIN pages p
                  ON p.key = i.key
                 AND p.sub_key = i.sub_key
                 AND p.start_index = i.start_index
                 AND p.end_index = i.end_index
                WHERE i.key = ?
                  AND i.sub_key = ?
                  AND i.user_id = ?
                ORDER BY p.fetched_at DESC
                LIMIT 1
                """,
                (key, sub_key, user_id),
            ).fetchone()
            if row is None:
                return None

            nick, score, start_index, position, fetched_at = row
            fetched_at_float = float(fetched_at)
            rank_config = get_rank_query_config()
            ttl = rank_config.page_cache_ttl_seconds
            is_stale = ttl <= 0 or time.time() - fetched_at_float > ttl
            stale_allowed = (
                rank_config.allow_stale_cache
                if allow_stale is None
                else allow_stale
            )
            if is_stale and not stale_allowed:
                return None
            return CachedRankLookup(
                id=user_id,
                nick=str(nick),
                score=int(score),
                rank_index=int(start_index) + int(position),
                fetched_at=fetched_at_float,
                is_stale=is_stale,
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
                    i.user_id,
                    i.nick,
                    i.score,
                    i.start_index,
                    i.position,
                    p.fetched_at
                FROM pages p
                JOIN items i
                  ON i.key = p.key
                 AND i.sub_key = p.sub_key
                 AND i.start_index = p.start_index
                 AND i.end_index = p.end_index
                 AND i.position = ? - p.start_index
                WHERE p.key = ?
                  AND p.sub_key = ?
                  AND p.start_index <= ?
                  AND p.end_index >= ?
                ORDER BY p.fetched_at DESC
                LIMIT 1
                """,
                (rank_index, key, sub_key, rank_index, rank_index),
            ).fetchone()
            if row is None:
                return None

            user_id, nick, score, start_index, position, fetched_at = row
            fetched_at_float = float(fetched_at)
            rank_config = get_rank_query_config()
            ttl = rank_config.page_cache_ttl_seconds
            is_stale = ttl <= 0 or time.time() - fetched_at_float > ttl
            stale_allowed = (
                rank_config.allow_stale_cache
                if allow_stale is None
                else allow_stale
            )
            if is_stale and not stale_allowed:
                return None
            return CachedRankLookup(
                id=int(user_id),
                nick=str(nick),
                score=int(score),
                rank_index=int(start_index) + int(position),
                fetched_at=fetched_at_float,
                is_stale=is_stale,
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
                    p.item_count AS expected_count,
                    COUNT(i.position) AS actual_count
                FROM pages p
                LEFT JOIN items i
                  ON i.key = p.key
                 AND i.sub_key = p.sub_key
                 AND i.start_index = p.start_index
                 AND i.end_index = p.end_index
                WHERE p.key = ?
                  AND p.sub_key = ?
                GROUP BY
                    p.start_index,
                    p.end_index,
                    p.fetched_at,
                    p.item_count
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
            is_stale=ttl <= 0 or now - float(fetched_at) > ttl,
            is_partial=int(actual_count) < int(expected_count),
        )
        for start_index, end_index, fetched_at, expected_count, actual_count in rows
    ]


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

    try:
        with _connect() as conn:
            user_ids = [
                int(getattr(item, "id", 0))
                for item in items
                if int(getattr(item, "id", 0)) > 0
            ]
            conn.execute(
                """
                REPLACE INTO pages (
                    key, sub_key, start_index, end_index, fetched_at, item_count
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    sub_key,
                    start,
                    end,
                    time.time() if fetched_at is None else fetched_at,
                    len(items),
                ),
            )
            conn.execute(
                """
                DELETE FROM items
                WHERE key = ?
                  AND sub_key = ?
                  AND start_index = ?
                  AND end_index = ?
                """,
                (key, sub_key, start, end),
            )
            if user_ids:
                placeholders = ",".join("?" for _ in user_ids)
                conn.execute(
                    f"""
                    DELETE FROM items
                    WHERE key = ?
                      AND sub_key = ?
                      AND user_id IN ({placeholders})
                      AND NOT (start_index = ? AND end_index = ?)
                    """,
                    (key, sub_key, *user_ids, start, end),
                )
            conn.executemany(
                """
                INSERT INTO items (
                    key, sub_key, start_index, end_index,
                    position, user_id, nick, score
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        key,
                        sub_key,
                        start,
                        end,
                        position,
                        int(getattr(item, "id", 0)),
                        str(getattr(item, "nick", "")),
                        int(getattr(item, "score", 0)),
                    )
                    for position, item in enumerate(items)
                ],
            )
    except sqlite3.Error as e:
        logger.warning(f"failed to write Seer rank page cache: {e}")
