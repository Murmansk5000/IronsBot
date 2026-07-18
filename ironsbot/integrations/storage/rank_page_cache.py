# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import sqlite3
import time
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import SqliteDatabase, SqliteMigration
from ironsbot.services.seer.rank_page_cache_models import (
    CachedRankItem,
    CachedRankLookup,
    CachedRankPage,
    CachedRankPageSummary,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS rank_players (
        user_id INTEGER PRIMARY KEY,
        nick TEXT NOT NULL DEFAULT '',
        updated_at REAL NOT NULL
    )
    """,
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
    """,
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
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_player_rank_facts_rank
    ON player_rank_facts (key, sub_key, rank_index)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_player_rank_facts_score
    ON player_rank_facts (key, sub_key, score DESC, rank_index)
    """,
)
_MIGRATIONS = (SqliteMigration(1, _SCHEMA),)
_LOGGER = logging.getLogger(__name__)


class SqliteRankPageCache:
    def __init__(
        self,
        path: Path,
        *,
        enabled: bool,
        ttl_seconds: int,
        allow_stale: bool,
    ) -> None:
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds
        self.allow_stale = allow_stale
        self._database = SqliteDatabase(path, migrations=_MIGRATIONS)

    def page(
        self,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        allow_stale: bool | None = None,
    ) -> CachedRankPage | None:
        if not self.enabled:
            return None
        try:
            with self._database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT fetched_at, expected_count
                    FROM rank_pages
                    WHERE key = ? AND sub_key = ?
                      AND start_index = ? AND end_index = ?
                    """,
                    (key, sub_key, start, end),
                ).fetchone()
                if row is None:
                    return None
                fetched_at, expected_count = row
                fetched_at = float(fetched_at)
                if self._reject_stale(fetched_at, allow_stale=allow_stale):
                    return None
                rows = conn.execute(
                    """
                    SELECT f.user_id,
                           COALESCE(NULLIF(f.display, ''), p.nick, ''),
                           f.score
                    FROM player_rank_facts f
                    LEFT JOIN rank_players p ON p.user_id = f.user_id
                    WHERE f.key = ? AND f.sub_key = ?
                      AND f.rank_index BETWEEN ? AND ?
                    ORDER BY f.rank_index
                    """,
                    (key, sub_key, start, end),
                ).fetchall()
                if len(rows) != int(expected_count):
                    return None
                return CachedRankPage(
                    [
                        CachedRankItem(int(user_id), str(nick), int(score))
                        for user_id, nick, score in rows
                    ],
                    fetched_at,
                )
        except sqlite3.Error as error:
            self._log_read_error(error)
            return None

    def item(
        self,
        *,
        key: int,
        sub_key: int,
        user_id: int,
        allow_stale: bool | None = None,
    ) -> CachedRankLookup | None:
        if not self.enabled:
            return None
        try:
            with self._database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT COALESCE(NULLIF(f.display, ''), p.nick, ''),
                           f.score, f.rank_index, f.fetched_at
                    FROM player_rank_facts f
                    LEFT JOIN rank_players p ON p.user_id = f.user_id
                    WHERE f.key = ? AND f.sub_key = ? AND f.user_id = ?
                    """,
                    (key, sub_key, user_id),
                ).fetchone()
            if row is None:
                return None
            nick, score, rank_index, fetched_at = row
            fetched_at = float(fetched_at)
            if self._reject_stale(fetched_at, allow_stale=allow_stale):
                return None
            return CachedRankLookup(
                user_id,
                str(nick),
                int(score),
                int(rank_index),
                fetched_at,
                self._is_stale(fetched_at),
            )
        except sqlite3.Error as error:
            self._log_read_error(error)
            return None

    def item_by_index(
        self,
        *,
        key: int,
        sub_key: int,
        rank_index: int,
        allow_stale: bool | None = None,
    ) -> CachedRankLookup | None:
        if not self.enabled:
            return None
        try:
            with self._database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT f.user_id,
                           COALESCE(NULLIF(f.display, ''), p.nick, ''),
                           f.score, f.fetched_at
                    FROM player_rank_facts f
                    LEFT JOIN rank_players p ON p.user_id = f.user_id
                    WHERE f.key = ? AND f.sub_key = ? AND f.rank_index = ?
                    """,
                    (key, sub_key, rank_index),
                ).fetchone()
            if row is None:
                return None
            user_id, nick, score, fetched_at = row
            fetched_at = float(fetched_at)
            if self._reject_stale(fetched_at, allow_stale=allow_stale):
                return None
            return CachedRankLookup(
                int(user_id),
                str(nick),
                int(score),
                rank_index,
                fetched_at,
                self._is_stale(fetched_at),
            )
        except sqlite3.Error as error:
            self._log_read_error(error)
            return None

    def summary(self, *, key: int, sub_key: int) -> list[CachedRankPageSummary]:
        if not self.enabled:
            return []
        try:
            with self._database.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT p.start_index, p.end_index, p.fetched_at,
                           p.expected_count, COUNT(f.user_id),
                           MIN(f.score), MAX(f.score)
                    FROM rank_pages p
                    LEFT JOIN player_rank_facts f
                      ON f.key = p.key AND f.sub_key = p.sub_key
                     AND f.rank_index BETWEEN p.start_index AND p.end_index
                    WHERE p.key = ? AND p.sub_key = ?
                    GROUP BY p.start_index, p.end_index, p.fetched_at,
                             p.expected_count
                    ORDER BY p.start_index, p.end_index
                    """,
                    (key, sub_key),
                ).fetchall()
        except sqlite3.Error as error:
            self._log_read_error(error)
            return []
        return [
            CachedRankPageSummary(
                start_index=int(start),
                end_index=int(end),
                item_count=int(actual),
                expected_count=int(expected),
                fetched_at=float(fetched_at),
                min_score=None if min_score is None else int(min_score),
                max_score=None if max_score is None else int(max_score),
                is_stale=self._is_stale(float(fetched_at)),
                is_partial=int(actual) < int(expected),
            )
            for start, end, fetched_at, expected, actual, min_score, max_score in rows
        ]

    def score_indexes(
        self,
        *,
        key: int,
        sub_key: int,
        score: int,
        start_index: int,
        end_index: int,
    ) -> list[int]:
        if not self.enabled:
            return []
        try:
            with self._database.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT rank_index
                    FROM player_rank_facts
                    WHERE key = ? AND sub_key = ? AND score = ?
                      AND rank_index >= ? AND rank_index < ?
                    ORDER BY rank_index
                    """,
                    (key, sub_key, score, start_index, end_index),
                ).fetchall()
        except sqlite3.Error as error:
            self._log_read_error(error)
            return []
        return [int(row[0]) for row in rows]

    def save(  # noqa: PLR0913
        self,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        items: Sequence[object],
        fetched_at: float | None = None,
    ) -> None:
        if not self.enabled:
            return
        timestamp = time.time() if fetched_at is None else fetched_at
        normalized = [
            (
                start + position,
                int(getattr(item, "id", 0)),
                str(getattr(item, "nick", "")),
                int(getattr(item, "score", 0)),
            )
            for position, item in enumerate(items)
            if int(getattr(item, "id", 0)) > 0
        ]
        user_ids = [user_id for _, user_id, _, _ in normalized]
        expected_count = max(0, end - start + 1)
        actual_count = len(set(user_ids))
        try:
            with self._database.connect() as conn:
                self._remove_overlaps(
                    conn,
                    key=key,
                    sub_key=sub_key,
                    start=start,
                    end=end,
                    user_ids=user_ids,
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
                        timestamp,
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
                    [(user_id, nick, timestamp) for _, user_id, nick, _ in normalized],
                )
                conn.executemany(
                    """
                    INSERT INTO player_rank_facts (
                        key, sub_key, user_id, rank_index, score, display,
                        fetched_at, source_start_index, source_end_index
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
                            timestamp,
                            start,
                            end,
                        )
                        for rank_index, user_id, nick, score in normalized
                    ],
                )
        except sqlite3.Error as error:
            _LOGGER.warning("failed to write Seer rank page cache: %s", error)

    @staticmethod
    def _remove_overlaps(  # noqa: PLR0913
        conn: sqlite3.Connection,
        *,
        key: int,
        sub_key: int,
        start: int,
        end: int,
        user_ids: Sequence[int],
    ) -> None:
        overlapping = conn.execute(
            """
            SELECT start_index, end_index
            FROM rank_pages
            WHERE key = ? AND sub_key = ?
              AND NOT (end_index < ? OR start_index > ?)
            """,
            (key, sub_key, start, end),
        ).fetchall()
        for old_start, old_end in overlapping:
            conn.execute(
                """
                DELETE FROM player_rank_facts
                WHERE key = ? AND sub_key = ?
                  AND source_start_index = ? AND source_end_index = ?
                """,
                (key, sub_key, old_start, old_end),
            )
            conn.execute(
                """
                DELETE FROM rank_pages
                WHERE key = ? AND sub_key = ?
                  AND start_index = ? AND end_index = ?
                """,
                (key, sub_key, old_start, old_end),
            )
        conn.execute(
            """
            DELETE FROM player_rank_facts
            WHERE key = ? AND sub_key = ? AND rank_index BETWEEN ? AND ?
            """,
            (key, sub_key, start, end),
        )
        if user_ids:
            conn.executemany(
                """
                DELETE FROM player_rank_facts
                WHERE key = ? AND sub_key = ? AND user_id = ?
                """,
                ((key, sub_key, user_id) for user_id in user_ids),
            )

    def _is_stale(self, fetched_at: float) -> bool:
        return self.ttl_seconds <= 0 or time.time() - fetched_at > self.ttl_seconds

    def _reject_stale(
        self,
        fetched_at: float,
        *,
        allow_stale: bool | None,
    ) -> bool:
        allowed = self.allow_stale if allow_stale is None else allow_stale
        return self._is_stale(fetched_at) and not allowed

    @staticmethod
    def _log_read_error(error: sqlite3.Error) -> None:
        _LOGGER.warning("failed to read Seer rank page cache: %s", error)
