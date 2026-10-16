import sqlite3
from pathlib import Path

import pytest

from ironsbot.integrations.storage.local_rank import SqliteLocalRankRepository
from ironsbot.integrations.storage.peak_season_migration import migrate_peak_season

OLD = 20260904
COMMON = 20260717
STAMP = "2026-09-18T12:34:56+08:00"


def legacy(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE players(user_id INTEGER PRIMARY KEY, nick TEXT,
                             updated_at TEXT, sampled_at TEXT);
        CREATE TABLE metrics(user_id INTEGER, metric_key TEXT, value INTEGER,
                             season_sub_key INTEGER, display TEXT,
                             PRIMARY KEY(user_id, metric_key));
    """)
    conn.execute("INSERT INTO players VALUES (700001, 'sample', ?, ?)", (STAMP, STAMP))
    return conn


@pytest.mark.parametrize(
    "scope,expected",
    [
        (-(COMMON * 100_000_000 + OLD), COMMON),
        (-(20261016 * 100_000_000 + 20261016), 20261016),
        (COMMON, None),
        (-(20260828 * 100_000_000 + OLD), None),
        (None, None),
    ],
)
def test_archives_and_converts_only_verified_four_mode_totals(
    tmp_path: Path,
    scope: int | None,
    expected: int | None,
) -> None:
    conn = legacy(tmp_path / "samples.sqlite")
    with conn:
        conn.execute(
            "INSERT INTO metrics VALUES (700001, 'peak_total_matches', 99, ?, 'old')",
            (scope,),
        )
        conn.execute(
            "INSERT INTO metrics VALUES (700001, 'peak_master', 200003, ?, 'rank')",
            (OLD,),
        )
    with conn:
        migrate_peak_season(conn)
    assert conn.execute(
        "SELECT season_sub_key FROM metrics WHERE metric_key='peak_master'"
    ).fetchone() == (COMMON,)
    total = conn.execute(
        "SELECT value, season_sub_key FROM metrics "
        "WHERE metric_key='peak_total_matches_v4'"
    ).fetchone()
    assert total == ((99, expected) if expected else None)
    assert conn.execute(
        "SELECT season_sub_key FROM legacy_peak_metrics WHERE metric_key='peak_master'"
    ).fetchone() == (OLD,)
    assert conn.execute("SELECT updated_at, sampled_at FROM players").fetchone() == (
        STAMP,
        STAMP,
    )
    before = conn.execute("SELECT * FROM metrics").fetchall()
    with conn:
        migrate_peak_season(conn)
    assert conn.execute("SELECT * FROM metrics").fetchall() == before
    assert conn.execute("SELECT count(*) FROM legacy_peak_metrics").fetchone() == (2,)
    conn.close()


def test_existing_common_record_is_not_overwritten_and_restart_is_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "samples.sqlite"
    with legacy(path) as conn:
        conn.execute(
            "INSERT INTO metrics VALUES (700001, 'peak_total_matches', 50, ?, 'old')",
            (-(COMMON * 100_000_000 + OLD),),
        )
        conn.execute(
            "INSERT INTO metrics VALUES "
            "(700001, 'peak_total_matches_v4', 90, 20261016, 'new')"
        )
    repository = SqliteLocalRankRepository(path, 100)
    repository.entries(
        "peak_total_matches_v4", limit=10, start_rank=1, season_sub_key=20261016
    )
    del repository
    repository = SqliteLocalRankRepository(path, 100)
    repository.entries(
        "peak_total_matches_v4", limit=10, start_rank=1, season_sub_key=20261016
    )
    del repository
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT value, season_sub_key FROM metrics "
            "WHERE metric_key='peak_total_matches_v4'"
        ).fetchone() == (90, 20261016)
        assert conn.execute("SELECT value FROM legacy_peak_metrics").fetchone() == (50,)


def test_migration_can_be_rolled_back_atomically(tmp_path: Path) -> None:
    conn = legacy(tmp_path / "samples.sqlite")
    with conn:
        conn.execute(
            "INSERT INTO metrics VALUES (700001, 'peak_master', 1, ?, '')", (OLD,)
        )
    with pytest.raises(RuntimeError), conn:
        migrate_peak_season(conn)
        message = "failed transaction"
        raise RuntimeError(message)
    assert conn.execute("SELECT season_sub_key FROM metrics").fetchone() == (OLD,)
    conn.close()
