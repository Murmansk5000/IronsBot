# SPDX-License-Identifier: GPL-3.0-or-later
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from nonebot.log import logger

from ..config import plugin_config


@dataclass(frozen=True, slots=True)
class CachedRankItem:
    id: int
    nick: str
    score: int


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
    fetched_at: float
    is_stale: bool = False


def _cache_path() -> Path:
    return plugin_config.seer_query_config.rank.page_cache_path


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
    return (
        plugin_config.seer_query_config.rank.page_cache
        and plugin_config.seer_query_config.rank.page_cache_ttl_seconds > 0
    )


def get_cached_rank_page(
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
) -> list[CachedRankItem] | None:
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
            if time.time() - float(fetched_at) > (
                plugin_config.seer_query_config.rank.page_cache_ttl_seconds
            ):
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

            return [
                CachedRankItem(id=int(user_id), nick=str(nick), score=int(score))
                for user_id, nick, score in rows
            ]
    except sqlite3.Error as e:
        logger.warning(f"failed to read Seer rank page cache: {e}")
        return None


def get_cached_rank_item(
    *,
    key: int,
    sub_key: int,
    user_id: int,
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
            is_stale = time.time() - fetched_at_float > (
                plugin_config.seer_query_config.rank.page_cache_ttl_seconds
            )
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
                SELECT start_index, end_index, fetched_at, item_count
                FROM pages
                WHERE key = ?
                  AND sub_key = ?
                ORDER BY start_index, end_index
                """,
                (key, sub_key),
            ).fetchall()
    except sqlite3.Error as e:
        logger.warning(f"failed to read Seer rank page cache summary: {e}")
        return []

    now = time.time()
    ttl = plugin_config.seer_query_config.rank.page_cache_ttl_seconds
    return [
        CachedRankPageSummary(
            start_index=int(start_index),
            end_index=int(end_index),
            fetched_at=float(fetched_at),
            item_count=int(item_count),
            is_stale=ttl <= 0 or now - float(fetched_at) > ttl,
        )
        for start_index, end_index, fetched_at, item_count in rows
    ]


def save_rank_page(
    *,
    key: int,
    sub_key: int,
    start: int,
    end: int,
    items: Sequence[object],
) -> None:
    if not _is_cache_enabled():
        return

    try:
        with _connect() as conn:
            conn.execute(
                """
                REPLACE INTO pages (
                    key, sub_key, start_index, end_index, fetched_at, item_count
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, sub_key, start, end, time.time(), len(items)),
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
