import asyncio
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from ironsbot.services.seer import local_rank_update
from ironsbot.services.seer.local_rank_formatting import format_metric_display
from ironsbot.services.seer.value_coercion import coerce_positive_int

EXPECTED_POSITIVE_INT = 12


def test_coerce_positive_int_rejects_invalid_and_non_positive_values() -> None:
    assert coerce_positive_int(str(EXPECTED_POSITIVE_INT)) == EXPECTED_POSITIVE_INT
    assert coerce_positive_int(0) is None
    assert coerce_positive_int(-1) is None
    assert coerce_positive_int("invalid") is None


def test_format_metric_display_decodes_peak_scores() -> None:
    assert format_metric_display("peak_standard", 400036) == "圣皇36星"
    assert format_metric_display("peak_standard", 400100) == "宇宙圣皇100星"
    assert format_metric_display("peak_wild", 300065) == "王者65星"
    assert format_metric_display("peak_expert", 1155) == "1155分"


def test_format_metric_display_keeps_cached_display_text() -> None:
    assert format_metric_display("peak_standard", 400036, "圣皇36星") == "圣皇36星"
    assert format_metric_display("book_score", 12345) == "12345"


def test_upsert_local_rank_metrics_clears_unconfirmed_peak_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE players (
            user_id INTEGER PRIMARY KEY,
            nick TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            sample_enabled INTEGER NOT NULL DEFAULT 1,
            sampled_at TEXT
        );
        CREATE TABLE metrics (
            user_id INTEGER NOT NULL,
            metric_key TEXT NOT NULL,
            value INTEGER NOT NULL,
            season_sub_key INTEGER,
            display TEXT,
            PRIMARY KEY (user_id, metric_key)
        );
        INSERT INTO players(user_id, nick, updated_at)
        VALUES (123456, '旧玩家', '2026-07-17T00:00:00+00:00');
        INSERT INTO metrics(user_id, metric_key, value, season_sub_key)
        VALUES
            (123456, 'peak_wild', 400100, 20260717),
            (123456, 'achievement_score', 5000, NULL);
        """
    )

    @contextmanager
    def fake_connect() -> Iterator[sqlite3.Connection]:
        yield conn

    monkeypatch.setattr(local_rank_update, "connect_local_rank_cache", fake_connect)

    asyncio.run(
        local_rank_update.upsert_local_rank_metrics(
            player_id=123456,
            nick="当前玩家",
            current_metrics={},
            peak_sub_key=20260717,
            clear_metric_keys=frozenset(("peak_wild",)),
        )
    )

    remaining = {
        row["metric_key"]
        for row in conn.execute(
            "SELECT metric_key FROM metrics WHERE user_id = 123456"
        )
    }
    assert remaining == {"achievement_score"}
