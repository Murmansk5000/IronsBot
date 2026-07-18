# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ironsbot.config.loader import get_app_config
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    ensure_sqlite_columns,
)
from ironsbot.services.seer.value_coercion import coerce_positive_int

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from pathlib import Path

    from ironsbot.services.seer.local_rank_metrics import MetricValue


def max_cached_players() -> int:
    return max(1, get_app_config().seer.local_rank.max_players)


def sqlite_cache_path() -> Path:
    return get_app_config().seer.local_rank.path


LOCAL_RANK_BASE_SCHEMA = (
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
LOCAL_RANK_INDEX_SCHEMA = (
    """
    CREATE INDEX IF NOT EXISTS idx_players_sample
    ON players(sample_enabled, user_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_metrics_rank
    ON metrics(metric_key, season_sub_key, value DESC, user_id)
    """,
)


def connect_local_rank_cache() -> AbstractContextManager[sqlite3.Connection]:
    return SqliteDatabase(
        sqlite_cache_path(),
        migrations=LOCAL_RANK_CACHE_MIGRATIONS,
        row_factory=sqlite3.Row,
    ).connect()


def _migrate_local_rank_cache(conn: sqlite3.Connection) -> None:
    added_columns = ensure_sqlite_columns(
        conn,
        table_name="players",
        columns={
            "sample_enabled": "sample_enabled INTEGER NOT NULL DEFAULT 1",
            "sampled_at": "sampled_at TEXT",
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
    for statement in LOCAL_RANK_INDEX_SCHEMA:
        conn.execute(statement)


LOCAL_RANK_CACHE_MIGRATIONS = (
    SqliteMigration(
        1,
        LOCAL_RANK_BASE_SCHEMA,
        _migrate_local_rank_cache,
    ),
)


def write_player_metrics(  # noqa: PLR0913
    conn: sqlite3.Connection,
    *,
    player_id: int,
    nick: str,
    metrics: dict[str, MetricValue],
    updated_at: str | None = None,
    sample_enabled: bool = True,
) -> None:
    timestamp = updated_at or datetime.now(timezone.utc).isoformat()
    sample_flag = 1 if sample_enabled else 0
    sampled_at = timestamp if sample_enabled else None
    conn.execute(
        """
        INSERT INTO players(user_id, nick, updated_at, sample_enabled, sampled_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            nick = excluded.nick,
            updated_at = CASE
                WHEN excluded.sample_enabled = 1 THEN excluded.updated_at
                ELSE players.updated_at
            END,
            sample_enabled = CASE
                WHEN excluded.sample_enabled = 1 THEN 1
                ELSE players.sample_enabled
            END,
            sampled_at = CASE
                WHEN excluded.sample_enabled = 1 THEN excluded.sampled_at
                ELSE players.sampled_at
            END
        """,
        (player_id, nick, timestamp, sample_flag, sampled_at),
    )
    for key, metric in metrics.items():
        value = coerce_positive_int(metric.get("value"))
        if value is None:
            continue

        season_sub_key = metric.get("season_sub_key")
        display = metric.get("display")
        conn.execute(
            """
            INSERT INTO metrics(user_id, metric_key, value, season_sub_key, display)
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


__all__ = [
    "connect_local_rank_cache",
    "max_cached_players",
    "sqlite_cache_path",
    "write_player_metrics",
]
