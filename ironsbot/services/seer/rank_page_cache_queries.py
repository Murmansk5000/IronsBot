# SPDX-License-Identifier: GPL-3.0-or-later
import sqlite3
import time

from nonebot.log import logger

from ironsbot.services.seer.rank_page_cache_models import (
    CachedRankItem,
    CachedRankLookup,
    CachedRankPage,
    CachedRankPageSummary,
)
from ironsbot.services.seer.rank_page_cache_policy import (
    connect_rank_page_cache,
    rank_page_cache_allows_stale,
    rank_page_cache_enabled,
    rank_page_cache_is_stale,
    rank_page_cache_ttl_seconds,
)


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
    if not rank_page_cache_enabled():
        return None

    try:
        with connect_rank_page_cache() as conn:
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
            if rank_page_cache_is_stale(
                fetched_at_float,
            ) and not rank_page_cache_allows_stale(
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
    if not rank_page_cache_enabled():
        return None

    try:
        with connect_rank_page_cache() as conn:
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
            stale = rank_page_cache_is_stale(fetched_at_float)
            if stale and not rank_page_cache_allows_stale(allow_stale=allow_stale):
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
    if not rank_page_cache_enabled():
        return None

    try:
        with connect_rank_page_cache() as conn:
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
            stale = rank_page_cache_is_stale(fetched_at_float)
            if stale and not rank_page_cache_allows_stale(allow_stale=allow_stale):
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
    if not rank_page_cache_enabled():
        return []

    try:
        with connect_rank_page_cache() as conn:
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
    ttl = rank_page_cache_ttl_seconds()
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
    if not rank_page_cache_enabled():
        return []

    try:
        with connect_rank_page_cache() as conn:
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
