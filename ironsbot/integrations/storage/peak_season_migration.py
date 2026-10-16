# SPDX-License-Identifier: GPL-3.0-or-later
"""One-time sample conversion; raw protocol caches are deliberately untouched."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

_LOGGER = logging.getLogger(__name__)
_OLD_MASTER = 20260904
_COMMON_SEASON = 20260717
_PAIR_BASE = 100_000_000
_OLD_TOTAL = "peak_total_matches"
_NEW_TOTAL = "peak_total_matches_v4"


def _total_season(scope: int | None) -> int | None:
    if scope is None or scope >= 0:
        return None
    regular, master = divmod(-scope, _PAIR_BASE)
    if regular != master and (regular, master) != (_COMMON_SEASON, _OLD_MASTER):
        return None
    try:
        datetime.strptime(str(regular), "%Y%m%d")  # noqa: DTZ007 - date validation only
    except ValueError:
        return None
    return regular


def migrate_peak_season(conn: sqlite3.Connection) -> None:
    """Called inside the SQLite migration transaction; never renew sample times."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_peak_metrics (
            user_id INTEGER NOT NULL,
            metric_key TEXT NOT NULL,
            value INTEGER NOT NULL,
            season_sub_key INTEGER,
            display TEXT,
            sampled_at TEXT,
            updated_at TEXT,
            PRIMARY KEY (user_id, metric_key)
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO legacy_peak_metrics
        SELECT m.user_id, m.metric_key, m.value, m.season_sub_key, m.display,
               p.sampled_at, p.updated_at
        FROM metrics m JOIN players p ON p.user_id = m.user_id
        WHERE (m.metric_key IN ('peak_master', 'peak_master_matches',
                               'peak_master_win_rate') AND m.season_sub_key = ?)
           OR m.metric_key = ?
        """,
        (_OLD_MASTER, _OLD_TOTAL),
    )
    conn.execute(
        """
        UPDATE metrics SET season_sub_key = ?
        WHERE metric_key IN ('peak_master', 'peak_master_matches',
                             'peak_master_win_rate') AND season_sub_key = ?
        """,
        (_COMMON_SEASON, _OLD_MASTER),
    )
    archived = 0
    for user_id, value, scope in conn.execute(
        "SELECT user_id, value, season_sub_key FROM metrics WHERE metric_key = ?",
        (_OLD_TOTAL,),
    ).fetchall():
        season = _total_season(scope)
        if season is None:
            archived += 1
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO metrics
            (user_id, metric_key, value, season_sub_key, display)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, _NEW_TOTAL, value, season, f"{value}场"),
        )
    conn.execute("DELETE FROM metrics WHERE metric_key = ?", (_OLD_TOTAL,))
    if archived:
        _LOGGER.warning(
            "Legacy peak totals archived without conversion: count=%s", archived
        )
