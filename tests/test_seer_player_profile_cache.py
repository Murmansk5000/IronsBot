from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.local_rank import SqliteLocalRankRepository

if TYPE_CHECKING:
    from pathlib import Path


PLAYER_ID = 123456
REG_TIME = 1_270_000_000
REGISTRATION_TIME_SCHEMA_VERSION = 2


def test_registration_time_cache_does_not_create_rank_sample(
    tmp_path: Path,
) -> None:
    path = tmp_path / "player-query-cache.sqlite"
    repository = SqliteLocalRankRepository(path, max_players=100)

    repository.upsert_registration_time(
        player_id=PLAYER_ID,
        nick="profile only",
        reg_time=REG_TIME,
    )

    assert repository.registration_time(PLAYER_ID) == REG_TIME
    assert repository.stats(()).player_count == 0
    assert repository.refresh_candidate_ids(limit=10, max_age_hours=0) == []


def test_registration_time_cache_expires_and_sample_can_be_upgraded(
    tmp_path: Path,
) -> None:
    path = tmp_path / "player-query-cache.sqlite"
    repository = SqliteLocalRankRepository(path, max_players=100)
    repository.upsert_registration_time(
        player_id=PLAYER_ID,
        nick="profile only",
        reg_time=REG_TIME,
    )
    stale_timestamp = (
        datetime.now(timezone.utc) - timedelta(days=31)
    ).isoformat()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE players SET reg_time_cached_at = ? WHERE user_id = ?",
            (stale_timestamp, PLAYER_ID),
        )

    assert repository.registration_time(PLAYER_ID) is None

    repository.upsert_metrics(
        player_id=PLAYER_ID,
        nick="sampled player",
        metrics={"achievement_score": {"value": 100}},
        clear_metric_keys=frozenset(),
        standing_inputs={"achievement_score": (100, None)},
    )
    assert repository.stats(()).player_count == 1
    assert repository.refresh_candidate_ids(limit=10, max_age_hours=0) == [
        PLAYER_ID
    ]


def test_existing_v1_database_migrates_registration_time_columns(
    tmp_path: Path,
) -> None:
    path = tmp_path / "player-query-cache.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE players (
                user_id INTEGER PRIMARY KEY,
                nick TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                sample_enabled INTEGER NOT NULL DEFAULT 1,
                sampled_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE metrics (
                user_id INTEGER NOT NULL,
                metric_key TEXT NOT NULL,
                value INTEGER NOT NULL,
                season_sub_key INTEGER,
                display TEXT,
                PRIMARY KEY (user_id, metric_key)
            )
            """
        )
        connection.execute("PRAGMA user_version = 1")

    repository = SqliteLocalRankRepository(path, max_players=100)
    repository.upsert_registration_time(
        player_id=PLAYER_ID,
        nick="migrated player",
        reg_time=REG_TIME,
    )

    assert repository.registration_time(PLAYER_ID) == REG_TIME
    with sqlite3.connect(path) as connection:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(players)")
        }
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    assert {"reg_time", "reg_time_cached_at"} <= columns
    assert version == REGISTRATION_TIME_SCHEMA_VERSION
