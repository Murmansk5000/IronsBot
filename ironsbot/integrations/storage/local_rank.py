# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    ensure_sqlite_columns,
)
from ironsbot.services.seer.local_rank_models import LocalRankCacheStats
from ironsbot.services.seer.value_coercion import coerce_positive_int

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from ironsbot.services.seer.local_rank import LocalRankRecord
    from ironsbot.services.seer.local_rank_metrics import MetricSpec, MetricValue

_BASE_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER PRIMARY KEY,
        nick TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metrics (
        user_id INTEGER NOT NULL,
        metric_key TEXT NOT NULL,
        value INTEGER NOT NULL,
        season_sub_key INTEGER,
        display TEXT,
        PRIMARY KEY (user_id, metric_key),
        FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
    )
    """,
)
_INDEX_SCHEMA = (
    """
    CREATE INDEX IF NOT EXISTS idx_players_sample
    ON players(sample_enabled, user_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_metrics_rank
    ON metrics(metric_key, season_sub_key, value DESC, user_id)
    """,
)


def _migrate(conn: sqlite3.Connection) -> None:
    added_columns = ensure_sqlite_columns(
        conn,
        table_name="players",
        columns={
            "sample_enabled": "sample_enabled INTEGER NOT NULL DEFAULT 1",
            "sampled_at": "sampled_at TEXT",
            "reg_time": "reg_time INTEGER",
            "reg_time_cached_at": "reg_time_cached_at TEXT",
        },
    )
    if "sampled_at" in added_columns:
        conn.execute(
            """
            UPDATE players
            SET sampled_at = updated_at
            WHERE sample_enabled = 1
              AND sampled_at IS NULL
            """
        )
    for statement in _INDEX_SCHEMA:
        conn.execute(statement)


_MIGRATIONS = (SqliteMigration(1, _BASE_SCHEMA, _migrate),)


class SqliteLocalRankRepository:
    def __init__(self, path: Path, max_players: int) -> None:
        self.max_players = max(1, max_players)
        self._database = SqliteDatabase(
            path,
            migrations=_MIGRATIONS,
            row_factory=sqlite3.Row,
        )

    def entries(
        self,
        metric_key: str,
        *,
        limit: int,
        start_rank: int,
        season_sub_key: int | None,
    ) -> tuple[list[LocalRankRecord], int]:
        requested_limit = max(0, limit)
        safe_start_rank = max(1, start_rank)
        fetch_limit = safe_start_rank + requested_limit - 1
        params = (metric_key, season_sub_key, season_sub_key)
        with self._database.connect() as conn:
            sample_count = self._count_metric_rows(
                conn,
                metric_key,
                season_sub_key,
            )
            rows = conn.execute(
                """
                SELECT m.value, p.user_id, p.nick, m.display
                FROM metrics m
                JOIN players p ON p.user_id = m.user_id
                WHERE m.metric_key = ?
                  AND m.value IS NOT NULL
                  AND ((? IS NULL AND m.season_sub_key IS NULL)
                       OR m.season_sub_key = ?)
                  AND p.sample_enabled = 1
                ORDER BY m.value DESC, p.user_id ASC
                LIMIT ?
                """,
                (*params, fetch_limit),
            ).fetchall()

        records: list[LocalRankRecord] = []
        last_value: int | None = None
        current_rank = 0
        for index, row in enumerate(rows, 1):
            value = int(row["value"])
            if value != last_value:
                current_rank = index
                last_value = value
            records.append(
                (
                    current_rank,
                    int(row["user_id"]),
                    str(row["nick"] or ""),
                    value,
                    str(row["display"] or ""),
                )
            )

        start_index = safe_start_rank - 1
        return records[start_index : start_index + requested_limit], sample_count

    def refresh_candidate_ids(
        self,
        *,
        limit: int,
        max_age_hours: int,
    ) -> list[int]:
        cutoff = (
            (
                datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
            ).isoformat()
            if max_age_hours > 0
            else None
        )
        with self._database.connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id
                FROM players
                WHERE sample_enabled = 1
                  AND (? IS NULL OR updated_at <= ?)
                ORDER BY updated_at ASC, user_id ASC
                LIMIT ?
                """,
                (cutoff, cutoff, max(0, limit)),
            ).fetchall()
        return [int(row["user_id"]) for row in rows]

    def stats(self, metrics: Sequence[MetricSpec]) -> LocalRankCacheStats:
        with self._database.connect() as conn:
            counts = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(sample_enabled), 0) AS sampled
                FROM players
                """
            ).fetchone()
            metric_counts = {
                spec.title: self._metric_count(conn, spec)
                for spec in metrics
            }
        return LocalRankCacheStats(
            player_count=int(counts["sampled"]),
            total_player_count=int(counts["total"]),
            max_players=self.max_players,
            metric_counts=metric_counts,
        )

    def can_cache(self, player_id: int) -> bool:
        with self._database.connect() as conn:
            is_sampled, player_count = self._sample_state(conn, player_id)
        return is_sampled or player_count < self.max_players

    def registration_time(
        self,
        player_id: int,
        *,
        max_age_days: int = 30,
    ) -> int | None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=max(1, max_age_days)
        )
        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT reg_time, reg_time_cached_at
                FROM players
                WHERE user_id = ?
                """,
                (player_id,),
            ).fetchone()
        if row is None or not row["reg_time"] or not row["reg_time_cached_at"]:
            return None
        try:
            cached_at = datetime.fromisoformat(str(row["reg_time_cached_at"]))
        except ValueError:
            return None
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        if cached_at < cutoff:
            return None
        return int(row["reg_time"])

    def upsert_registration_time(
        self,
        *,
        player_id: int,
        nick: str,
        reg_time: int,
    ) -> None:
        if reg_time <= 0:
            return
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._database.connect() as conn:
            conn.execute(
                """
                INSERT INTO players(
                    user_id, nick, updated_at, sample_enabled, sampled_at,
                    reg_time, reg_time_cached_at
                )
                VALUES (?, ?, ?, 0, NULL, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    nick = excluded.nick,
                    reg_time = excluded.reg_time,
                    reg_time_cached_at = excluded.reg_time_cached_at
                """,
                (player_id, nick, timestamp, reg_time, timestamp),
            )

    def delete_player(self, player_id: int) -> None:
        with self._database.connect() as conn:
            conn.execute("DELETE FROM metrics WHERE user_id = ?", (player_id,))
            conn.execute("DELETE FROM players WHERE user_id = ?", (player_id,))

    def upsert_metrics(
        self,
        *,
        player_id: int,
        nick: str,
        metrics: Mapping[str, MetricValue],
        clear_metric_keys: frozenset[str],
        standing_inputs: Mapping[str, tuple[int, int | None]],
    ) -> dict[str, tuple[int, int, int]]:
        with self._database.connect() as conn:
            is_sampled, player_count = self._sample_state(conn, player_id)
            include_current = not is_sampled and player_count >= self.max_players
            if not include_current:
                if clear_metric_keys:
                    conn.executemany(
                        "DELETE FROM metrics WHERE user_id = ? AND metric_key = ?",
                        ((player_id, key) for key in clear_metric_keys),
                    )
                self._write_metrics(
                    conn,
                    player_id=player_id,
                    nick=nick,
                    metrics=metrics,
                )
            return {
                key: self._metric_standing(
                    conn,
                    metric_key=key,
                    current_value=value,
                    season_sub_key=season_sub_key,
                    include_current=include_current,
                )
                for key, (value, season_sub_key) in standing_inputs.items()
            }

    @staticmethod
    def _sample_state(
        conn: sqlite3.Connection,
        player_id: int,
    ) -> tuple[bool, int]:
        row = conn.execute(
            """
            SELECT EXISTS(
                       SELECT 1 FROM players
                       WHERE user_id = ? AND sample_enabled = 1
                   ) AS sampled,
                   (
                       SELECT COUNT(*) FROM players
                       WHERE sample_enabled = 1
                   ) AS player_count
            """,
            (player_id,),
        ).fetchone()
        return bool(row["sampled"]), int(row["player_count"])

    def _count_metric_rows(
        self,
        conn: sqlite3.Connection,
        metric_key: str,
        season_sub_key: int | None,
    ) -> int:
        return int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM metrics m
                JOIN players p ON p.user_id = m.user_id
                WHERE m.metric_key = ?
                  AND m.value IS NOT NULL
                  AND ((? IS NULL AND m.season_sub_key IS NULL)
                       OR m.season_sub_key = ?)
                  AND p.sample_enabled = 1
                """,
                (metric_key, season_sub_key, season_sub_key),
            ).fetchone()[0]
        )

    def _metric_count(
        self,
        conn: sqlite3.Connection,
        spec: MetricSpec,
    ) -> int:
        if not spec.season_limited:
            return self._count_metric_rows(conn, spec.key, None)
        return int(
            conn.execute(
                """
                SELECT COUNT(*) FROM metrics
                WHERE metric_key = ?
                  AND value IS NOT NULL
                  AND season_sub_key IS NOT NULL
                """,
                (spec.key,),
            ).fetchone()[0]
        )

    def _metric_standing(
        self,
        conn: sqlite3.Connection,
        *,
        metric_key: str,
        current_value: int,
        season_sub_key: int | None,
        include_current: bool,
    ) -> tuple[int, int, int]:
        row = conn.execute(
            """
            SELECT COUNT(*) AS sample_count,
                   SUM(CASE WHEN m.value > ? THEN 1 ELSE 0 END) AS greater_count,
                   SUM(CASE WHEN m.value = ? THEN 1 ELSE 0 END) AS tie_count
            FROM metrics m
            JOIN players p ON p.user_id = m.user_id
            WHERE m.metric_key = ?
              AND m.value IS NOT NULL
              AND p.sample_enabled = 1
              AND ((? IS NULL AND m.season_sub_key IS NULL)
                   OR m.season_sub_key = ?)
            """,
            (
                current_value,
                current_value,
                metric_key,
                season_sub_key,
                season_sub_key,
            ),
        ).fetchone()
        sample_count = int(row["sample_count"])
        greater_count = int(row["greater_count"] or 0)
        tie_count = int(row["tie_count"] or 0)
        if include_current:
            sample_count += 1
            tie_count += 1
        return sample_count, 1 + greater_count, tie_count

    @staticmethod
    def _write_metrics(
        conn: sqlite3.Connection,
        *,
        player_id: int,
        nick: str,
        metrics: Mapping[str, MetricValue],
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO players(user_id, nick, updated_at, sample_enabled, sampled_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                nick = excluded.nick,
                updated_at = excluded.updated_at,
                sample_enabled = 1,
                sampled_at = excluded.sampled_at
            """,
            (player_id, nick, timestamp, timestamp),
        )
        for key, metric in metrics.items():
            value = coerce_positive_int(metric.get("value"))
            if value is None:
                continue
            season_sub_key = metric.get("season_sub_key")
            display = metric.get("display")
            conn.execute(
                """
                INSERT INTO metrics(
                    user_id, metric_key, value, season_sub_key, display
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, metric_key) DO UPDATE SET
                    value = excluded.value,
                    season_sub_key = excluded.season_sub_key,
                    display = excluded.display
                """,
                (
                    player_id,
                    key,
                    value,
                    season_sub_key if isinstance(season_sub_key, int) else None,
                    None if display in (None, "") else str(display),
                ),
            )
