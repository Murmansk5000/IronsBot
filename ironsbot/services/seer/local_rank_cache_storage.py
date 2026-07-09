# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from ironsbot.config import get_app_config
from ironsbot.services.seer.local_rank_metrics import MetricValue, positive_int
from ironsbot.shared.sqlite import ensure_sqlite_column, open_sqlite_schema

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ironsbot.shared.sqlite import RowFactory


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


@contextmanager
def connect_local_rank_cache() -> Iterator[sqlite3.Connection]:
    with open_sqlite_schema(
        sqlite_cache_path(),
        LOCAL_RANK_BASE_SCHEMA,
        row_factory=cast("RowFactory", sqlite3.Row),
    ) as conn:
        ensure_local_rank_cache_schema(conn)
        yield conn


def ensure_local_rank_cache_schema(conn: sqlite3.Connection) -> None:
    ensure_sqlite_column(
        conn,
        table_name="players",
        column_name="sample_enabled",
        column_definition="sample_enabled INTEGER NOT NULL DEFAULT 1",
    )
    if ensure_sqlite_column(
        conn,
        table_name="players",
        column_name="sampled_at",
        column_definition="sampled_at TEXT",
    ):
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
        value = positive_int(metric.get("value"))
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
    "ensure_local_rank_cache_schema",
    "max_cached_players",
    "sqlite_cache_path",
    "write_player_metrics",
]
